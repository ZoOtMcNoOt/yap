use std::{
    io::{Read, Write},
    net::TcpListener,
    thread,
};

use super::*;

fn sha(character: char) -> String {
    character.to_string().repeat(64)
}

fn request() -> LibrarianRequest {
    LibrarianRequest::new("reviewed launch decision".into(), 3, Some(sha('a'))).unwrap()
}

fn complete_view() -> serde_json::Value {
    serde_json::json!({
        "schemaVersion": 1,
        "requestId": format!("librarian-query-{}", "1".repeat(32)),
        "status": "complete",
        "evidencePack": {
            "operation": "search",
            "generationSha256": sha('a'),
            "permissionHash": sha('b'),
            "authorizationHash": sha('c'),
            "evidenceSha256": "7ea81dd81d6a7fa36e513ae325b9602f33998d1cf5cb5755de6b332adcbb2961",
            "items": [{
                "conceptId": "meetings/launch-review",
                "sourceRevision": "revision-1",
                "contentSha256": "c1a307f1754d0900800485eac54c4742a844b0dfad81ccc98bd5c1de2563cb3e",
                "charStart": 0,
                "charEnd": 47,
                "text": "The reviewed launch decision requires approval."
            }],
            "outputBudgetExhausted": false
        }
    })
}

#[test]
fn request_owns_only_search_bounds_and_optional_generation() {
    assert_eq!(
        serde_json::to_value(request()).unwrap(),
        serde_json::json!({
            "schemaVersion": 1,
            "searchText": "reviewed launch decision",
            "maximumResults": 3,
            "expectedGenerationSha256": sha('a')
        })
    );
    assert!(LibrarianRequest::new("___".into(), 3, None).is_err());
    assert!(LibrarianRequest::new(" query".into(), 3, None).is_err());
    assert!(LibrarianRequest::new("query".into(), 0, None).is_err());
    assert!(LibrarianRequest::new("query".into(), 6, None).is_err());
    assert!(LibrarianRequest::new("query".into(), 3, Some(sha('A'))).is_err());
}

#[test]
fn authenticated_client_submits_and_decodes_one_bounded_view() {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut headers = [0_u8; 4096];
        let count = stream.read(&mut headers).unwrap();
        let request_text = String::from_utf8_lossy(&headers[..count]);
        assert!(request_text.starts_with("POST /v1/librarian-queries HTTP/1.1\r\n"));
        assert!(request_text
            .to_ascii_lowercase()
            .contains("authorization: bearer private-token"));
        let body = serde_json::json!({
            "schemaVersion": 1,
            "requestId": format!("librarian-query-{}", "1".repeat(32)),
            "status": "queued"
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

    let client = LibrarianApiClient::new(
        AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "private-token"),
        &format!("http://{address}"),
    )
    .unwrap();
    let view = tauri::async_runtime::block_on(client.submit(&request())).unwrap();
    assert_eq!(view.status, LibrarianQueryStatus::Queued);
    server.join().unwrap();
}

#[test]
fn complete_evidence_hash_and_terminal_shapes_fail_closed() {
    let view = decode_job_view(serde_json::to_vec(&complete_view()).unwrap()).unwrap();
    assert_eq!(view.status, LibrarianQueryStatus::Complete);
    assert_eq!(view.evidence_pack.unwrap().items.len(), 1);

    let mut malformed = complete_view();
    malformed["evidencePack"]["evidenceSha256"] = serde_json::json!(sha('d'));
    assert!(decode_job_view(serde_json::to_vec(&malformed).unwrap()).is_err());

    let mut malformed = complete_view();
    malformed["status"] = serde_json::json!("running");
    assert!(decode_job_view(serde_json::to_vec(&malformed).unwrap()).is_err());

    let malformed = serde_json::json!({
        "schemaVersion": 1,
        "requestId": format!("librarian-query-{}", "1".repeat(32)),
        "status": "evidence-unavailable"
    });
    assert!(decode_job_view(serde_json::to_vec(&malformed).unwrap()).is_err());
}

#[test]
fn complete_response_must_match_requested_generation_and_limit() {
    let view = decode_job_view(serde_json::to_vec(&complete_view()).unwrap()).unwrap();
    assert!(view.matches_request(&request()));
    let different = LibrarianRequest::new("query".into(), 1, Some(sha('d'))).unwrap();
    assert!(!view.matches_request(&different));
}
