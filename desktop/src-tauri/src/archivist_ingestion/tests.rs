use std::{
    io::{Read, Write},
    net::TcpListener,
    thread,
};

use super::*;
use crate::server_connector::{
    archivist_connection_lease_for_test, AuthenticatedRequestDispatcher,
};

fn request() -> ArchivistIngestionRequest {
    ArchivistIngestionRequest::new("server-job-1".into(), "a".repeat(64)).unwrap()
}

fn view(status: ArchivistIngestionStatus, reason: Option<&str>) -> ArchivistIngestionJobView {
    ArchivistIngestionJobView::for_test(
        format!("archivist-ingestion-{}", "1".repeat(32)),
        status,
        "server-job-1".into(),
        "a".repeat(64),
        reason.map(str::to_owned),
    )
}

fn serve_json(stream: &mut std::net::TcpStream, status: &str, body: serde_json::Value) {
    let body = body.to_string();
    write!(
        stream,
        "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len(),
    )
    .unwrap();
}

#[test]
fn owner_preserves_source_identity_and_monotonic_lifecycle() {
    let owner = ArchivistIngestionOwner::new();
    owner
        .insert_for_test(
            request(),
            archivist_connection_lease_for_test(),
            view(ArchivistIngestionStatus::Queued, None),
        )
        .unwrap();
    let owned = owner
        .request(&format!("archivist-ingestion-{}", "1".repeat(32)))
        .unwrap();
    assert_eq!(
        owner
            .update(&owned, view(ArchivistIngestionStatus::Running, None))
            .unwrap()
            .status,
        ArchivistIngestionStatus::Running
    );
    let running = owner.request(&owned.latest.request_id).unwrap();
    assert!(owner
        .update(&running, view(ArchivistIngestionStatus::Queued, None))
        .is_err());
}

#[test]
fn terminal_owner_state_is_exact_and_reclaimable() {
    let owner = ArchivistIngestionOwner::new();
    owner
        .insert_for_test(
            request(),
            archivist_connection_lease_for_test(),
            view(
                ArchivistIngestionStatus::Cancelled,
                Some("client-cancelled"),
            ),
        )
        .unwrap();
    let owned = owner
        .request(&format!("archivist-ingestion-{}", "1".repeat(32)))
        .unwrap();
    assert_eq!(
        owner
            .update(
                &owned,
                view(
                    ArchivistIngestionStatus::Cancelled,
                    Some("client-cancelled"),
                ),
            )
            .unwrap(),
        owned.latest
    );
    assert!(owner
        .update(
            &owned,
            view(
                ArchivistIngestionStatus::Failed,
                Some("storage-unavailable")
            ),
        )
        .is_err());

    let mut state = owner.state.lock().unwrap();
    reclaim_terminal_requests(&mut state.requests);
    assert!(state.requests.is_empty());
}

#[test]
fn terminal_cancellation_supersedes_a_concurrent_active_poll() {
    let owner = ArchivistIngestionOwner::new();
    owner
        .insert_for_test(
            request(),
            archivist_connection_lease_for_test(),
            view(ArchivistIngestionStatus::Queued, None),
        )
        .unwrap();
    let queued = owner
        .request(&format!("archivist-ingestion-{}", "1".repeat(32)))
        .unwrap();
    owner
        .update(&queued, view(ArchivistIngestionStatus::Running, None))
        .unwrap();

    let terminal = owner
        .reconcile_terminal(
            &queued,
            view(
                ArchivistIngestionStatus::Cancelled,
                Some("client-cancelled"),
            ),
        )
        .unwrap();

    assert_eq!(terminal.status, ArchivistIngestionStatus::Cancelled);
    assert_eq!(
        owner.request(&terminal.request_id).unwrap().latest,
        terminal
    );
}

#[test]
fn containment_rejects_a_terminal_for_another_request_or_source() {
    let expected_request_id = format!("archivist-ingestion-{}", "1".repeat(32));
    let other_request_id = format!("archivist-ingestion-{}", "2".repeat(32));
    assert!(exact_containment_view(
        ArchivistIngestionJobView::for_test(
            other_request_id,
            ArchivistIngestionStatus::Cancelled,
            "server-job-1".into(),
            "a".repeat(64),
            Some("client-cancelled".into()),
        ),
        &expected_request_id,
        &request(),
    )
    .is_err());
    assert!(exact_containment_view(
        ArchivistIngestionJobView::for_test(
            expected_request_id.clone(),
            ArchivistIngestionStatus::Cancelled,
            "server-job-2".into(),
            "a".repeat(64),
            Some("client-cancelled".into()),
        ),
        &expected_request_id,
        &request(),
    )
    .is_err());
}

#[test]
fn cancellation_waits_for_terminal_before_releasing_native_ownership() {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let request_id = format!("archivist-ingestion-{}", "1".repeat(32));
    let server_request_id = request_id.clone();
    let server = thread::spawn(move || {
        for (method, status, reason) in [
            ("DELETE", "202 Accepted", None),
            ("GET", "200 OK", Some("client-cancelled")),
        ] {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request_bytes = [0_u8; 4096];
            let count = stream.read(&mut request_bytes).unwrap();
            let request_text = String::from_utf8_lossy(&request_bytes[..count]);
            assert!(request_text.starts_with(&format!(
                "{method} /v1/archivist-ingestions/{server_request_id} HTTP/1.1\r\n"
            )));
            let mut body = serde_json::json!({
                "schemaVersion": 1,
                "requestId": server_request_id,
                "status": if reason.is_some() { "cancelled" } else { "cancellation-requested" },
                "jobId": "server-job-1",
                "resultSha256": "a".repeat(64),
            });
            if let Some(reason) = reason {
                body["reason"] = serde_json::json!(reason);
            }
            serve_json(&mut stream, status, body);
        }
    });
    let client = ArchivistApiClient::new(
        AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "private-token"),
        &format!("http://{address}"),
    )
    .unwrap();

    let terminal = tauri::async_runtime::block_on(contain_submitted_ingestion(
        &client,
        &request_id,
        &request(),
    ))
    .unwrap();

    assert_eq!(terminal.status, ArchivistIngestionStatus::Cancelled);
    assert_eq!(terminal.reason.as_deref(), Some("client-cancelled"));
    server.join().unwrap();
}
