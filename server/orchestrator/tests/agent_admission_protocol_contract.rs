mod support;

use std::time::Duration;

use serde_json::{json, Value};
use support::{cancellation_token, ready_scheduler, request_id, scheduler, source_sha};
use yap_server_orchestrator::process_agent_admission_request;

#[test]
fn submit_admits_only_to_the_exact_ready_route() {
    let mut ready = ready_scheduler();
    assert_eq!(
        send(&mut ready, scribe_submit(0, "alice"), Duration::ZERO),
        json!({
            "outcome": "admitted",
            "schemaVersion": 1,
            "route": "rapid-automation",
            "providerGeneration": 1,
            "queueDurationMs": 0,
        })
    );

    let mut unavailable = scheduler();
    assert_eq!(
        send(&mut unavailable, scribe_submit(1, "alice"), Duration::ZERO,),
        json!({
            "outcome": "provider-unavailable",
            "schemaVersion": 1,
            "route": "rapid-automation",
        })
    );
}

#[test]
fn queued_owner_observes_queue_inclusive_admission_time() {
    let mut scheduler = ready_scheduler();
    assert_eq!(
        send(&mut scheduler, scribe_submit(0, "alice"), Duration::ZERO,)["outcome"],
        "admitted"
    );
    assert_eq!(
        send(&mut scheduler, scribe_submit(1, "alice"), Duration::ZERO,),
        json!({"outcome": "queued", "schemaVersion": 1})
    );

    assert_eq!(
        send(
            &mut scheduler,
            control("complete", 0),
            Duration::from_millis(20),
        ),
        json!({"outcome": "completed", "schemaVersion": 1})
    );
    assert_eq!(
        send(
            &mut scheduler,
            control("status", 1),
            Duration::from_millis(25),
        ),
        json!({
            "outcome": "admitted",
            "schemaVersion": 1,
            "route": "rapid-automation",
            "providerGeneration": 1,
            "queueDurationMs": 25,
        })
    );
}

#[test]
fn cancellation_requires_worker_acknowledgement_and_is_idempotent() {
    let mut scheduler = ready_scheduler();
    send(&mut scheduler, scribe_submit(0, "alice"), Duration::ZERO);
    let requested = json!({
        "outcome": "cancellation-requested",
        "schemaVersion": 1,
        "reason": "client-requested",
    });
    assert_eq!(
        send(
            &mut scheduler,
            control("cancel", 0),
            Duration::from_millis(1),
        ),
        requested
    );
    assert_eq!(
        send(
            &mut scheduler,
            control("complete", 0),
            Duration::from_millis(2),
        ),
        requested
    );
    let terminal = json!({"outcome": "cancelled", "schemaVersion": 1});
    assert_eq!(
        send(
            &mut scheduler,
            control("acknowledge-cancellation", 0),
            Duration::from_millis(3),
        ),
        terminal
    );
    assert_eq!(
        send(
            &mut scheduler,
            control("acknowledge-cancellation", 0),
            Duration::from_millis(4),
        ),
        terminal
    );
}

#[test]
fn control_tokens_do_not_disclose_another_request() {
    let mut scheduler = ready_scheduler();
    send(&mut scheduler, scribe_submit(0, "alice"), Duration::ZERO);
    let mut unauthorized = control("status", 0);
    unauthorized["cancellationToken"] = json!(cancellation_token(99));
    let not_found = json!({
        "outcome": "not-found-or-unauthorized",
        "schemaVersion": 1,
    });
    assert_eq!(
        send(&mut scheduler, unauthorized, Duration::from_millis(1)),
        not_found
    );
    assert_eq!(
        send(
            &mut scheduler,
            json!({
                "schemaVersion": 1,
                "command": "status",
                "requestId": "missing-request",
                "cancellationToken": cancellation_token(99),
            }),
            Duration::from_millis(1),
        ),
        not_found
    );
}

#[test]
fn malformed_schema_role_deadline_and_framing_fail_without_mutation() {
    let mut scheduler = ready_scheduler();
    let invalid = json!({"outcome": "invalid-request", "schemaVersion": 1});

    let mut wrong_schema = scribe_submit(0, "alice");
    wrong_schema["schemaVersion"] = json!(2);
    assert_eq!(send(&mut scheduler, wrong_schema, Duration::ZERO), invalid);

    let mut wrong_route = scribe_submit(0, "alice");
    wrong_route["route"] = json!("complex-orchestration");
    assert_eq!(send(&mut scheduler, wrong_route, Duration::ZERO), invalid);

    let mut excessive_deadline = scribe_submit(0, "alice");
    excessive_deadline["remainingDeadlineMs"] = json!(60_001);
    assert_eq!(
        send(&mut scheduler, excessive_deadline, Duration::ZERO),
        invalid
    );

    let mut unknown = scribe_submit(0, "alice");
    unknown["automaticFallback"] = json!(true);
    assert_eq!(send(&mut scheduler, unknown, Duration::ZERO), invalid);

    let without_newline = serde_json::to_vec(&scribe_submit(0, "alice")).unwrap();
    assert_eq!(
        parse_response(process_agent_admission_request(
            &mut scheduler,
            &without_newline,
            Duration::ZERO,
        )),
        invalid
    );
    assert_eq!(
        send(&mut scheduler, control("status", 0), Duration::ZERO,)["outcome"],
        "not-found-or-unauthorized"
    );
}

fn scribe_submit(index: usize, subject: &str) -> Value {
    json!({
        "schemaVersion": 1,
        "command": "submit",
        "requestId": request_id(index),
        "tenantId": "tenant-a",
        "subjectId": subject,
        "purpose": "transcript-correct",
        "role": "scribe",
        "sourceSha256": source_sha(index),
        "route": "rapid-automation",
        "schedulingClass": "hot",
        "cancellationToken": cancellation_token(index),
        "remainingDeadlineMs": 60_000,
    })
}

fn control(command: &str, index: usize) -> Value {
    json!({
        "schemaVersion": 1,
        "command": command,
        "requestId": request_id(index),
        "cancellationToken": cancellation_token(index),
    })
}

fn send(
    scheduler: &mut yap_server_orchestrator::AgentAdmissionScheduler,
    value: Value,
    observed_at: Duration,
) -> Value {
    let mut bytes = serde_json::to_vec(&value).unwrap();
    bytes.push(b'\n');
    parse_response(process_agent_admission_request(
        scheduler,
        &bytes,
        observed_at,
    ))
}

fn parse_response(bytes: Vec<u8>) -> Value {
    assert!(bytes.ends_with(b"\n"));
    serde_json::from_slice(&bytes).unwrap()
}
