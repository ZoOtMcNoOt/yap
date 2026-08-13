use std::{
    io::{Read, Write},
    net::TcpListener,
    thread,
};

use super::*;

fn sha(character: char) -> String {
    character.to_string().repeat(64)
}

fn request() -> ArchivistIngestionRequest {
    ArchivistIngestionRequest::new("server-job-1".into(), sha('a')).unwrap()
}

#[test]
fn request_contains_only_server_job_and_result_identity() {
    assert_eq!(
        serde_json::to_value(request()).unwrap(),
        serde_json::json!({
            "schemaVersion": 1,
            "jobId": "server-job-1",
            "expectedResultSha256": sha('a')
        })
    );
    assert!(ArchivistIngestionRequest::new("job/1".into(), sha('a')).is_err());
    assert!(ArchivistIngestionRequest::new("job-1".into(), sha('A')).is_err());
}

#[test]
fn authenticated_client_submits_and_decodes_a_bound_job_view() {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut headers = [0_u8; 4096];
        let count = stream.read(&mut headers).unwrap();
        let request_text = String::from_utf8_lossy(&headers[..count]);
        assert!(request_text.starts_with("POST /v1/archivist-ingestions HTTP/1.1\r\n"));
        assert!(request_text
            .to_ascii_lowercase()
            .contains("authorization: bearer private-token"));
        let body = serde_json::json!({
            "schemaVersion": 1,
            "requestId": format!("archivist-ingestion-{}", "1".repeat(32)),
            "status": "queued",
            "jobId": "server-job-1",
            "resultSha256": sha('a')
        })
        .to_string();
        write!(
            stream,
            "HTTP/1.1 202 Accepted\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            body.len(),
            body
        )
        .unwrap();
    });

    let client = ArchivistApiClient::new(
        AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "private-token"),
        &format!("http://{address}"),
    )
    .unwrap();
    let view = tauri::async_runtime::block_on(client.submit(&request())).unwrap();
    assert_eq!(view.status, ArchivistIngestionStatus::Queued);
    assert!(view.matches_request(&request()));
    server.join().unwrap();
}

#[test]
fn staged_and_terminal_shapes_fail_closed() {
    let staged = serde_json::json!({
        "schemaVersion": 1,
        "requestId": format!("archivist-ingestion-{}", "1".repeat(32)),
        "status": "staged",
        "jobId": "server-job-1",
        "resultSha256": sha('a'),
        "captureSha256": sha('b'),
        "sourceAdmissionSha256": sha('c'),
        "generationSha256": sha('d'),
        "conceptCount": 2,
        "permissionCount": 1
    });
    assert!(decode_job_view(serde_json::to_vec(&staged).unwrap()).is_ok());

    let mut malformed = staged.clone();
    malformed["captureSha256"] = serde_json::Value::Null;
    assert!(decode_job_view(serde_json::to_vec(&malformed).unwrap()).is_err());

    let mut malformed = staged;
    malformed["status"] = serde_json::json!("failed");
    malformed["reason"] = serde_json::json!("storage-unavailable");
    assert!(decode_job_view(serde_json::to_vec(&malformed).unwrap()).is_err());
}
