use super::*;
use crate::server_connector::{
    transcript_correction::{
        sha256_text, TranscriptCorrectionJobView, TranscriptCorrectionSegment,
        TranscriptCorrectionStatus,
    },
    transcript_correction_connection_lease_for_test, AuthenticatedRequestDispatcher,
};
use std::{
    io::{Read, Write},
    net::TcpListener,
    thread,
};

fn source() -> TrustedTranscriptCorrectionSource {
    let text = "Dose is twenty five mg.";
    TrustedTranscriptCorrectionSource {
        kind: TranscriptCorrectionSourceKind::Live,
        output_path: std::env::temp_dir().join("live-owned-correction.txt"),
        source_revision_sha256: "a".repeat(64),
        text: text.into(),
        segments: vec![TranscriptCorrectionSegment::new(
            "segment-0001".into(),
            0,
            text.chars().count(),
            0,
            1_500,
            "en-US".into(),
            text.into(),
            sha256_text(text),
        )
        .unwrap()],
    }
}

fn view(request_id: usize, status: TranscriptCorrectionStatus) -> TranscriptCorrectionJobView {
    let (applied, corrected_text, reason) = match status {
        TranscriptCorrectionStatus::Complete => (true, Some("Dose is 25 mg.".to_string()), None),
        TranscriptCorrectionStatus::Failed => (false, None, Some("model-unavailable".to_string())),
        _ => (false, None, None),
    };
    TranscriptCorrectionJobView::for_test(
        format!("correction-{request_id}"),
        status,
        "a".repeat(64),
        "b".repeat(64),
        applied,
        corrected_text,
        reason,
    )
}

#[test]
fn stale_poll_or_cancel_response_cannot_overwrite_newer_state() {
    let owner = TranscriptCorrectionOwner::new();
    let queued = view(1, TranscriptCorrectionStatus::Queued);
    owner
        .insert_for_test(
            source(),
            transcript_correction_connection_lease_for_test(),
            queued.clone(),
        )
        .expect("insert owned request");
    let first_snapshot = owner.request(&queued.request_id).unwrap();
    let running = view(1, TranscriptCorrectionStatus::Running);
    assert_eq!(
        owner.update(&first_snapshot, running.clone()).unwrap(),
        running
    );

    let stale_cancelled = view(1, TranscriptCorrectionStatus::Cancelled);
    assert_eq!(
        owner.update(&first_snapshot, stale_cancelled).unwrap(),
        running
    );
    assert_eq!(owner.request(&queued.request_id).unwrap().latest, running);
}

#[test]
fn terminal_and_backward_lifecycle_transitions_fail_closed() {
    let owner = TranscriptCorrectionOwner::new();
    let running = view(2, TranscriptCorrectionStatus::Running);
    owner
        .insert_for_test(
            source(),
            transcript_correction_connection_lease_for_test(),
            running.clone(),
        )
        .expect("insert owned request");
    let snapshot = owner.request(&running.request_id).unwrap();
    assert!(owner
        .update(&snapshot, view(2, TranscriptCorrectionStatus::Queued))
        .is_err());

    let complete = view(2, TranscriptCorrectionStatus::Complete);
    assert_eq!(owner.update(&snapshot, complete.clone()).unwrap(), complete);
    let terminal = owner.request(&running.request_id).unwrap();
    assert!(owner
        .update(&terminal, view(2, TranscriptCorrectionStatus::Failed))
        .is_err());
}

#[test]
fn terminology_snapshot_identity_cannot_change_during_polling() {
    let owner = TranscriptCorrectionOwner::new();
    let queued = view(3, TranscriptCorrectionStatus::Queued);
    owner
        .insert_for_test(
            source(),
            transcript_correction_connection_lease_for_test(),
            queued.clone(),
        )
        .unwrap();
    let snapshot = owner.request(&queued.request_id).unwrap();
    let mut changed = view(3, TranscriptCorrectionStatus::Running);
    changed.terminology_snapshot_sha256 = "d".repeat(64);

    assert!(owner.update(&snapshot, changed).is_err());
    assert_eq!(owner.request(&queued.request_id).unwrap().latest, queued);
}

#[test]
fn completed_unsaved_requests_are_not_evicted_under_device_pressure() {
    let owner = TranscriptCorrectionOwner::new();
    for index in 0..MAXIMUM_OWNED_REQUESTS {
        owner
            .insert_for_test(
                source(),
                transcript_correction_connection_lease_for_test(),
                view(index, TranscriptCorrectionStatus::Complete),
            )
            .unwrap();
    }
    assert!(owner
        .insert_for_test(
            source(),
            transcript_correction_connection_lease_for_test(),
            view(MAXIMUM_OWNED_REQUESTS, TranscriptCorrectionStatus::Queued),
        )
        .is_err());
    assert_eq!(
        owner.state.lock().expect("owner lock").requests.len(),
        MAXIMUM_OWNED_REQUESTS
    );
}

#[test]
fn completed_unchanged_requests_are_reclaimed_under_device_pressure() {
    let owner = TranscriptCorrectionOwner::new();
    for index in 0..MAXIMUM_OWNED_REQUESTS {
        let mut complete = view(index, TranscriptCorrectionStatus::Complete);
        complete.applied = false;
        complete.corrected_text = Some(source().text);
        complete.reason = Some("uncertain".into());
        owner
            .insert_for_test(
                source(),
                transcript_correction_connection_lease_for_test(),
                complete,
            )
            .unwrap();
    }

    let replacement = view(MAXIMUM_OWNED_REQUESTS, TranscriptCorrectionStatus::Queued);
    owner
        .insert_for_test(
            source(),
            transcript_correction_connection_lease_for_test(),
            replacement.clone(),
        )
        .unwrap();
    let state = owner.state.lock().expect("owner lock");
    assert_eq!(state.requests.len(), 1);
    assert_eq!(state.requests[&replacement.request_id].latest, replacement);
}

#[test]
fn concurrent_submission_reservations_share_the_exact_device_bound() {
    let owner = TranscriptCorrectionOwner::new();
    let mut reservations = (0..MAXIMUM_OWNED_REQUESTS)
        .map(|_| owner.reserve_submission().unwrap())
        .collect::<Vec<_>>();
    assert!(owner.reserve_submission().is_err());

    drop(reservations.pop());
    assert!(owner.reserve_submission().is_ok());
}

#[test]
fn failed_requests_are_reclaimed_but_unknown_ids_remain_unowned() {
    let owner = TranscriptCorrectionOwner::new();
    for index in 0..MAXIMUM_OWNED_REQUESTS {
        let status = if index == 0 {
            TranscriptCorrectionStatus::Failed
        } else {
            TranscriptCorrectionStatus::Running
        };
        owner
            .insert_for_test(
                source(),
                transcript_correction_connection_lease_for_test(),
                view(index, status),
            )
            .unwrap();
    }
    let replacement = view(MAXIMUM_OWNED_REQUESTS, TranscriptCorrectionStatus::Queued);
    owner
        .insert_for_test(
            source(),
            transcript_correction_connection_lease_for_test(),
            replacement.clone(),
        )
        .unwrap();
    assert!(owner.request("correction-0").is_err());
    assert_eq!(
        owner.request(&replacement.request_id).unwrap().latest,
        replacement
    );
    assert!(owner.request("correction-other-user").is_err());
}

#[test]
fn shutdown_snapshot_includes_only_active_owned_requests() {
    let owner = TranscriptCorrectionOwner::new();
    for (index, status) in [
        TranscriptCorrectionStatus::Queued,
        TranscriptCorrectionStatus::Running,
        TranscriptCorrectionStatus::CancellationRequested,
        TranscriptCorrectionStatus::Cancelled,
        TranscriptCorrectionStatus::Complete,
        TranscriptCorrectionStatus::Failed,
    ]
    .into_iter()
    .enumerate()
    {
        owner
            .insert_for_test(
                source(),
                transcript_correction_connection_lease_for_test(),
                view(index, status),
            )
            .unwrap();
    }

    assert_eq!(owner.active_request_count(), 3);
}

#[test]
fn accepted_request_without_local_ownership_is_cancelled_and_observed_terminal() {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let request_id = "agent-0123456789abcdef0123456789abcdef";
    let server_request_id = request_id.to_owned();
    let server = thread::spawn(move || {
        for (index, expected_method) in ["DELETE", "GET"].into_iter().enumerate() {
            let (mut stream, _) = listener.accept().unwrap();
            let mut bytes = [0_u8; 4096];
            let count = stream.read(&mut bytes).unwrap();
            let request = String::from_utf8_lossy(&bytes[..count]);
            assert!(request.starts_with(&format!(
                "{expected_method} /v1/transcript-corrections/{server_request_id} HTTP/1.1\r\n"
            )));
            let status = if index == 0 {
                "cancellation-requested"
            } else {
                "cancelled"
            };
            let body = serde_json::json!({
                "schemaVersion": 1,
                "requestId": server_request_id,
                "status": status,
                "sourceRevisionSha256": "a".repeat(64),
                "sourceSha256": "b".repeat(64),
                "terminologySnapshotSha256": "c".repeat(64),
                "applied": false
            })
            .to_string();
            let response_status = if index == 0 { "202 Accepted" } else { "200 OK" };
            write!(
                stream,
                "HTTP/1.1 {response_status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            )
            .unwrap();
        }
    });
    let client = TranscriptCorrectionApiClient::new(
        AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "private-token"),
        &format!("http://{address}"),
    )
    .unwrap();

    tauri::async_runtime::block_on(contain_unowned_submitted_correction(&client, request_id))
        .unwrap();
    server.join().unwrap();
}
