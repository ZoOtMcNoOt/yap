mod support;

use std::time::Duration;

use support::{cancellation_token, ready_scheduler, ready_snapshot, request_id, scheduler, work};
use yap_server_orchestrator::{
    AdmissionDecision, AdmissionEvent, AdmissionStatus, AgentRole, CancellationDecision,
    CancellationReason, ExecutionRoute, LifecycleState, ProviderService, TerminalOutcome,
};

#[test]
fn invalid_provider_identity_is_contained_and_reported_on_the_next_dispatch() {
    let mut scheduler = ready_scheduler();
    let active = work(0, "alice", AgentRole::Scribe, Duration::from_secs(60));
    let queued = work(1, "bob", AgentRole::Scribe, Duration::from_secs(60));
    scheduler.submit(active.clone(), Duration::ZERO);
    scheduler.submit(queued.clone(), Duration::ZERO);
    scheduler.dispatch(Duration::ZERO);

    let mut invalid = ready_snapshot(ProviderService::RapidAutomation, 1);
    invalid.profile_sha256 = "f".repeat(64);
    assert!(scheduler.observe_provider(&invalid).is_err());
    assert_eq!(
        scheduler.status(active.request_id(), active.cancellation_token()),
        AdmissionStatus::ActiveCancellationRequested(CancellationReason::ProviderUnavailable)
    );
    assert_eq!(
        scheduler.status(queued.request_id(), queued.cancellation_token()),
        AdmissionStatus::Terminal(TerminalOutcome::ProviderUnavailable(
            ExecutionRoute::RapidAutomation,
        ))
    );

    let events = scheduler.dispatch(Duration::from_millis(1));
    assert!(
        events.contains(&AdmissionEvent::ActiveCancellationRequested {
            request_id: active.request_id().to_owned(),
            reason: CancellationReason::ProviderUnavailable,
        })
    );
    assert!(events.contains(&AdmissionEvent::ProviderUnavailable {
        request_id: queued.request_id().to_owned(),
        route: ExecutionRoute::RapidAutomation,
    }));
    assert_eq!(scheduler.active_count(), 1);
}

#[test]
fn provider_generation_high_water_mark_survives_non_ready_states() {
    let mut scheduler = scheduler();
    scheduler
        .observe_provider(&ready_snapshot(ProviderService::RapidAutomation, 2))
        .unwrap();

    let mut stopped = ready_snapshot(ProviderService::RapidAutomation, 2);
    stopped.state = LifecycleState::Stopped;
    scheduler.observe_provider(&stopped).unwrap();

    assert!(scheduler
        .observe_provider(&ready_snapshot(ProviderService::RapidAutomation, 1))
        .is_err());
    assert_eq!(
        scheduler.submit(
            work(0, "alice", AgentRole::Scribe, Duration::from_secs(60)),
            Duration::ZERO,
        ),
        AdmissionDecision::ProviderUnavailable(ExecutionRoute::RapidAutomation)
    );
}

#[test]
fn cancellation_and_completion_tokens_are_non_disclosing() {
    let mut scheduler = ready_scheduler();
    let request = work(0, "alice", AgentRole::Scribe, Duration::from_secs(60));
    scheduler.submit(request.clone(), Duration::ZERO);

    assert_eq!(
        scheduler.status(request.request_id(), &cancellation_token(99)),
        AdmissionStatus::NotFoundOrUnauthorized
    );
    assert_eq!(
        scheduler.cancel(request.request_id(), &cancellation_token(99)),
        CancellationDecision::NotFoundOrUnauthorized
    );
    scheduler.dispatch(Duration::ZERO);

    let wrong_completion = scheduler
        .complete(request.request_id(), &cancellation_token(99))
        .unwrap_err()
        .to_string();
    let missing_completion = scheduler
        .complete("missing-request", &cancellation_token(99))
        .unwrap_err()
        .to_string();
    assert_eq!(wrong_completion, missing_completion);

    scheduler
        .complete(request.request_id(), request.cancellation_token())
        .unwrap();
    assert_eq!(
        scheduler.status(request.request_id(), request.cancellation_token()),
        AdmissionStatus::Terminal(TerminalOutcome::Completed)
    );
    scheduler
        .complete(request.request_id(), request.cancellation_token())
        .unwrap();
}

#[test]
fn duplicate_submission_is_non_disclosing_without_the_original_token() {
    let mut scheduler = ready_scheduler();
    let request = work(0, "alice", AgentRole::Scribe, Duration::from_secs(60));
    assert_eq!(
        scheduler.submit(request.clone(), Duration::ZERO),
        AdmissionDecision::Queued
    );

    let wrong_token = yap_server_orchestrator::AgentWorkRequest::new(
        request.request_id().to_owned(),
        request.owner().clone(),
        request.purpose(),
        request.role(),
        request.source_sha256().to_owned(),
        request.route(),
        request.scheduling_class(),
        cancellation_token(99),
        request.deadline_at(),
    )
    .unwrap();
    assert_eq!(
        scheduler.submit(wrong_token, Duration::ZERO),
        AdmissionDecision::NotFoundOrUnauthorized
    );
    assert_eq!(
        scheduler.submit(request, Duration::ZERO),
        AdmissionDecision::DuplicateRequest
    );
}

#[test]
fn queue_duration_and_provider_generation_are_bound_to_the_lease() {
    let mut scheduler = ready_scheduler();
    let request = work(0, "alice", AgentRole::Scribe, Duration::from_secs(60));
    assert_eq!(
        scheduler.submit(request, Duration::from_millis(10)),
        AdmissionDecision::Queued
    );

    let events = scheduler.dispatch(Duration::from_millis(35));
    let AdmissionEvent::Admitted(lease) = &events[0] else {
        panic!("request was not admitted");
    };
    assert_eq!(lease.queue_duration(), Duration::from_millis(25));
    assert_eq!(lease.provider_generation(), Some(1));
    assert_eq!(lease.admitted_at(), Duration::from_millis(35));
}

#[test]
fn per_owner_bound_counts_active_and_pending_work_together() {
    let mut scheduler = ready_scheduler();
    for index in 0..4 {
        assert_eq!(
            scheduler.submit(
                work(index, "alice", AgentRole::Student, Duration::from_secs(60)),
                Duration::ZERO,
            ),
            AdmissionDecision::Queued
        );
    }
    scheduler.dispatch(Duration::ZERO);
    assert_eq!(scheduler.active_count(), 1);
    assert_eq!(
        scheduler.submit(
            work(5, "alice", AgentRole::Student, Duration::from_secs(60)),
            Duration::ZERO,
        ),
        AdmissionDecision::OwnerQueueFull
    );
}

#[test]
fn active_deadline_requires_acknowledged_cancellation_before_capacity_is_released() {
    let mut scheduler = ready_scheduler();
    let request = work(0, "alice", AgentRole::Scribe, Duration::from_secs(5));
    scheduler.submit(request.clone(), Duration::ZERO);
    assert_eq!(
        scheduler.status(request.request_id(), request.cancellation_token()),
        AdmissionStatus::Queued
    );
    scheduler.dispatch(Duration::ZERO);
    assert!(matches!(
        scheduler.status(request.request_id(), request.cancellation_token()),
        AdmissionStatus::Admitted(_)
    ));

    assert_eq!(
        scheduler.dispatch(Duration::from_secs(5)),
        vec![AdmissionEvent::ActiveCancellationRequested {
            request_id: request.request_id().to_owned(),
            reason: CancellationReason::DeadlineExceeded,
        }]
    );
    assert_eq!(
        scheduler.status(request.request_id(), request.cancellation_token()),
        AdmissionStatus::ActiveCancellationRequested(CancellationReason::DeadlineExceeded)
    );
    assert!(scheduler
        .complete(request.request_id(), request.cancellation_token())
        .is_err());
    assert_eq!(scheduler.active_count(), 1);

    scheduler
        .acknowledge_cancellation(request.request_id(), request.cancellation_token())
        .unwrap();
    assert_eq!(scheduler.active_count(), 0);
    assert_eq!(
        scheduler.status(request.request_id(), request.cancellation_token()),
        AdmissionStatus::Terminal(TerminalOutcome::DeadlineExceeded)
    );
}

#[test]
fn active_cancellation_acknowledgement_is_non_disclosing() {
    let mut scheduler = ready_scheduler();
    let request = work(0, "alice", AgentRole::Scribe, Duration::from_secs(60));
    scheduler.submit(request.clone(), Duration::ZERO);
    scheduler.dispatch(Duration::ZERO);
    scheduler.cancel(request.request_id(), request.cancellation_token());

    let wrong_token = scheduler
        .acknowledge_cancellation(request.request_id(), &cancellation_token(99))
        .unwrap_err()
        .to_string();
    let missing = scheduler
        .acknowledge_cancellation("missing-request", &cancellation_token(99))
        .unwrap_err()
        .to_string();
    assert_eq!(wrong_token, missing);
    assert_eq!(scheduler.active_count(), 1);
}

#[test]
fn backwards_generation_disruption_is_deferred_when_observation_fails() {
    let mut scheduler = scheduler();
    scheduler
        .observe_provider(&ready_snapshot(ProviderService::RapidAutomation, 2))
        .unwrap();
    let active = work(0, "alice", AgentRole::Scribe, Duration::from_secs(60));
    scheduler.submit(active.clone(), Duration::ZERO);
    scheduler.dispatch(Duration::ZERO);

    assert!(scheduler
        .observe_provider(&ready_snapshot(ProviderService::RapidAutomation, 1))
        .is_err());
    assert_eq!(
        scheduler.dispatch(Duration::from_millis(1)),
        vec![AdmissionEvent::ActiveCancellationRequested {
            request_id: request_id(0),
            reason: CancellationReason::ProviderUnavailable,
        }]
    );
}
