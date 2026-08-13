mod support;

use std::time::Duration;

use support::{
    admitted_ids, cancellation_token, ready_scheduler, ready_snapshot, request_id, scheduler,
    terminal_ids, work,
};
use yap_server_orchestrator::{
    AdmissionDecision, AdmissionEvent, AgentRole, CancellationDecision, CancellationReason,
    ExecutionRoute, ProviderService,
};

#[test]
fn model_work_is_rejected_until_its_exact_warm_service_is_ready() {
    let mut scheduler = scheduler();
    let decision = scheduler.submit(
        work(0, "alice", AgentRole::Scribe, Duration::from_secs(30)),
        Duration::ZERO,
    );
    assert_eq!(
        decision,
        AdmissionDecision::ProviderUnavailable(ExecutionRoute::RapidAutomation)
    );

    scheduler
        .observe_provider(&ready_snapshot(ProviderService::RapidAutomation, 1))
        .unwrap();
    assert_eq!(
        scheduler.submit(
            work(1, "alice", AgentRole::Scribe, Duration::from_secs(30)),
            Duration::ZERO,
        ),
        AdmissionDecision::Queued
    );
    let admitted = admitted_ids(scheduler.dispatch(Duration::ZERO));
    assert_eq!(admitted, vec![request_id(1)]);
}

#[test]
fn exact_full_profile_route_capacities_admit_four_rapid_and_eight_complex() {
    let mut scheduler = ready_scheduler();
    for index in 0..5 {
        assert_eq!(
            scheduler.submit(
                work(
                    index,
                    &format!("rapid-owner-{index}"),
                    AgentRole::Scribe,
                    Duration::from_secs(60),
                ),
                Duration::ZERO,
            ),
            AdmissionDecision::Queued
        );
    }
    for index in 10..19 {
        assert_eq!(
            scheduler.submit(
                work(
                    index,
                    &format!("complex-owner-{index}"),
                    AgentRole::Curator,
                    Duration::from_secs(60),
                ),
                Duration::ZERO,
            ),
            AdmissionDecision::Queued
        );
    }

    let admitted = admitted_ids(scheduler.dispatch(Duration::ZERO));
    assert_eq!(
        admitted
            .iter()
            .filter(|id| {
                id.strip_prefix("agent-request-")
                    .unwrap()
                    .parse::<usize>()
                    .unwrap()
                    < 10
            })
            .count(),
        4
    );
    assert_eq!(admitted.len(), 12);
    assert!(!admitted.contains(&request_id(4)));
    assert!(!admitted.contains(&request_id(18)));

    scheduler
        .complete(&request_id(0), &cancellation_token(0))
        .unwrap();
    scheduler
        .complete(&request_id(10), &cancellation_token(10))
        .unwrap();
    let replacements = admitted_ids(scheduler.dispatch(Duration::from_millis(1)));
    assert_eq!(replacements, vec![request_id(4), request_id(18)]);
}

#[test]
fn owners_are_round_robin_with_one_active_request_per_owner() {
    let mut scheduler = ready_scheduler();
    for (index, subject) in [(0, "alice"), (1, "alice"), (2, "bob"), (3, "bob")] {
        assert_eq!(
            scheduler.submit(
                work(index, subject, AgentRole::Student, Duration::from_secs(60),),
                Duration::ZERO,
            ),
            AdmissionDecision::Queued
        );
    }

    let first = admitted_ids(scheduler.dispatch(Duration::ZERO));
    assert_eq!(first, vec![request_id(0), request_id(2)]);
    scheduler
        .complete(&request_id(0), &cancellation_token(0))
        .unwrap();
    let second = admitted_ids(scheduler.dispatch(Duration::from_millis(1)));
    assert_eq!(second, vec![request_id(1)]);
    scheduler
        .complete(&request_id(2), &cancellation_token(2))
        .unwrap();
    let third = admitted_ids(scheduler.dispatch(Duration::from_millis(2)));
    assert_eq!(third, vec![request_id(3)]);
    scheduler
        .complete(&request_id(1), &cancellation_token(1))
        .unwrap();
    let fourth = admitted_ids(scheduler.dispatch(Duration::from_millis(3)));
    assert!(fourth.is_empty());
}

#[test]
fn hot_work_yields_after_eight_dispatches_to_ready_background_work() {
    let mut scheduler = ready_scheduler();
    for index in 0..9 {
        assert_eq!(
            scheduler.submit(
                work(
                    index,
                    &format!("hot-{index}"),
                    AgentRole::Scribe,
                    Duration::from_secs(60),
                ),
                Duration::ZERO,
            ),
            AdmissionDecision::Queued
        );
    }
    assert_eq!(
        scheduler.submit(
            work(20, "student", AgentRole::Student, Duration::from_secs(60)),
            Duration::ZERO,
        ),
        AdmissionDecision::Queued
    );

    let mut order = Vec::new();
    for tick in 0..3 {
        let admitted = admitted_ids(scheduler.dispatch(Duration::from_millis(tick)));
        assert!(admitted.len() <= 4);
        for request in &admitted {
            let index = request
                .strip_prefix("agent-request-")
                .unwrap()
                .parse::<usize>()
                .unwrap();
            scheduler
                .complete(request, &cancellation_token(index))
                .unwrap();
        }
        order.extend(admitted);
    }
    assert_eq!(order[..8], (0..8).map(request_id).collect::<Vec<_>>());
    assert_eq!(order[8], request_id(20));
}

#[test]
fn queue_and_owner_bounds_return_typed_overload() {
    let mut scheduler = ready_scheduler();
    for index in 0..4 {
        assert_eq!(
            scheduler.submit(
                work(index, "alice", AgentRole::Student, Duration::from_secs(60),),
                Duration::ZERO,
            ),
            AdmissionDecision::Queued
        );
    }
    assert_eq!(
        scheduler.submit(
            work(5, "alice", AgentRole::Student, Duration::from_secs(60)),
            Duration::ZERO,
        ),
        AdmissionDecision::OwnerQueueFull
    );

    for index in 10..71 {
        let decision = scheduler.submit(
            work(
                index,
                &format!("owner-{index}"),
                AgentRole::Student,
                Duration::from_secs(60),
            ),
            Duration::ZERO,
        );
        if decision == AdmissionDecision::QueueFull {
            return;
        }
        assert_eq!(decision, AdmissionDecision::Queued);
    }
    panic!("global queue bound was not enforced");
}

#[test]
fn deadline_and_cancellation_are_acknowledged_without_releasing_active_early() {
    let mut scheduler = ready_scheduler();
    let active = work(0, "alice", AgentRole::Scribe, Duration::from_secs(60));
    let queued = work(1, "alice", AgentRole::Scribe, Duration::from_secs(5));
    assert_eq!(
        scheduler.submit(active.clone(), Duration::ZERO),
        AdmissionDecision::Queued
    );
    assert_eq!(
        scheduler.submit(queued.clone(), Duration::ZERO),
        AdmissionDecision::Queued
    );
    assert_eq!(
        admitted_ids(scheduler.dispatch(Duration::ZERO)),
        vec![active.request_id().to_owned()]
    );

    assert_eq!(
        terminal_ids(scheduler.dispatch(Duration::from_secs(5))),
        vec![queued.request_id().to_owned()]
    );
    assert_eq!(
        scheduler.cancel(active.request_id(), active.cancellation_token()),
        CancellationDecision::ActiveCancellationRequested
    );
    assert!(scheduler.dispatch(Duration::from_secs(6)).is_empty());
    scheduler
        .acknowledge_cancellation(active.request_id(), active.cancellation_token())
        .unwrap();
    assert_eq!(scheduler.active_count(), 0);
}

#[test]
fn provider_generation_change_cancels_active_and_fails_queued_without_fallback() {
    let mut scheduler = ready_scheduler();
    let active = work(0, "alice", AgentRole::Scribe, Duration::from_secs(60));
    let queued = work(1, "alice", AgentRole::Scribe, Duration::from_secs(60));
    scheduler.submit(active.clone(), Duration::ZERO);
    scheduler.submit(queued.clone(), Duration::ZERO);
    scheduler.dispatch(Duration::ZERO);

    let events = scheduler
        .observe_provider(&ready_snapshot(ProviderService::RapidAutomation, 2))
        .unwrap();
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
    assert!(scheduler.dispatch(Duration::from_millis(1)).is_empty());
}

#[test]
fn auditor_is_admitted_only_when_every_non_idle_work_item_is_absent() {
    let mut scheduler = ready_scheduler();
    let librarian = work(0, "alice", AgentRole::Librarian, Duration::from_secs(60));
    let auditor = work(1, "bob", AgentRole::Auditor, Duration::from_secs(60));
    scheduler.submit(librarian.clone(), Duration::ZERO);
    scheduler.submit(auditor.clone(), Duration::ZERO);

    let first = admitted_ids(scheduler.dispatch(Duration::ZERO));
    assert_eq!(first, vec![librarian.request_id().to_owned()]);
    scheduler
        .complete(librarian.request_id(), librarian.cancellation_token())
        .unwrap();
    let second = admitted_ids(scheduler.dispatch(Duration::from_millis(1)));
    assert_eq!(second, vec![auditor.request_id().to_owned()]);
}
