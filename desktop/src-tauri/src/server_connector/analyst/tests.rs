use std::{
    io::{Read, Write},
    net::TcpListener,
    thread,
};

use super::*;

fn sha(character: char) -> String {
    character.to_string().repeat(64)
}

fn request() -> AnalystRequest {
    AnalystRequest::new("What was approved?".into(), 3, Some(sha('a'))).unwrap()
}

fn complete_view() -> serde_json::Value {
    serde_json::json!({
        "schemaVersion": 1,
        "requestId": format!("analyst-answer-{}", "1".repeat(32)),
        "status": "complete",
        "citedAnswer": {
            "schemaVersion": 1,
            "answer": "The reviewed launch decision requires approval.",
            "citations": [{
                "conceptId": "meetings/launch-review",
                "sourceRevision": "revision-1",
                "contentSha256": sha('a'),
                "charStart": 8,
                "charEnd": 55,
                "text": "The reviewed launch decision requires approval."
            }],
            "answerSha256": "c1a307f1754d0900800485eac54c4742a844b0dfad81ccc98bd5c1de2563cb3e",
            "citationSha256": "3e0225c50f8b2f7f1ab6e63b03573d0307552595c60127d67813629ce9191088",
            "evidenceSha256": sha('d')
        }
    })
}

#[test]
fn request_owns_only_question_bounds_and_optional_generation() {
    assert_eq!(
        serde_json::to_value(request()).unwrap(),
        serde_json::json!({
            "schemaVersion": 1,
            "question": "What was approved?",
            "maximumResults": 3,
            "expectedGenerationSha256": sha('a')
        })
    );
    assert!(AnalystRequest::new("___".into(), 3, None).is_err());
    assert!(AnalystRequest::new(" question".into(), 3, None).is_err());
    assert!(AnalystRequest::new("question".into(), 0, None).is_err());
    assert!(AnalystRequest::new("question".into(), 6, None).is_err());
    assert!(AnalystRequest::new("question".into(), 3, Some(sha('A'))).is_err());
}

#[test]
fn answer_requires_exact_server_derived_text_citations_and_hashes() {
    let value = complete_view();
    let view = decode_job_view(serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(view.matches_request(&request()));

    for field in ["answer", "answerSha256", "citationSha256"] {
        let mut malformed = value.clone();
        malformed["citedAnswer"][field] = serde_json::json!(sha('e'));
        assert!(decode_job_view(serde_json::to_vec(&malformed).unwrap()).is_err());
    }
    let mut malformed = value;
    malformed["citedAnswer"]["citations"][0]["text"] = serde_json::json!("different");
    assert!(decode_job_view(serde_json::to_vec(&malformed).unwrap()).is_err());
}

#[test]
fn authenticated_submit_uses_only_the_frozen_analyst_endpoint() {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut bytes = [0_u8; 8192];
        let count = stream.read(&mut bytes).unwrap();
        let request_text = String::from_utf8_lossy(&bytes[..count]);
        assert!(request_text.starts_with("POST /v1/analyst-answers HTTP/1.1\r\n"));
        assert!(request_text
            .to_ascii_lowercase()
            .contains("authorization: bearer private-token"));
        assert!(request_text.contains("\"question\":\"What was approved?\""));
        let body = serde_json::json!({
            "schemaVersion": 1,
            "requestId": format!("analyst-answer-{}", "1".repeat(32)),
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

    let client = AnalystApiClient::new(
        AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "private-token"),
        &format!("http://{address}"),
    )
    .unwrap();
    let view = tauri::async_runtime::block_on(client.submit(&request())).unwrap();
    assert_eq!(view.status, AnalystAnswerStatus::Queued);
    server.join().unwrap();
}

#[test]
fn status_and_cancel_reject_a_different_response_identity() {
    for (method, response_status, analyst_status) in [
        ("GET", "200 OK", "running"),
        ("DELETE", "202 Accepted", "cancellation-requested"),
    ] {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let address = listener.local_addr().unwrap();
        let expected_request_id = format!("analyst-answer-{}", "1".repeat(32));
        let expected_path = format!("/v1/analyst-answers/{expected_request_id}");
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut bytes = [0_u8; 8192];
            let count = stream.read(&mut bytes).unwrap();
            let request_text = String::from_utf8_lossy(&bytes[..count]);
            assert!(request_text.starts_with(&format!("{method} {expected_path} HTTP/1.1\r\n")));
            let body = serde_json::json!({
                "schemaVersion": 1,
                "requestId": format!("analyst-answer-{}", "2".repeat(32)),
                "status": analyst_status
            })
            .to_string();
            write!(
                stream,
                "HTTP/1.1 {response_status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            )
            .unwrap();
        });

        let client = AnalystApiClient::new(
            AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "private-token"),
            &format!("http://{address}"),
        )
        .unwrap();
        let result = if method == "GET" {
            tauri::async_runtime::block_on(client.status(&expected_request_id))
        } else {
            tauri::async_runtime::block_on(client.cancel(&expected_request_id))
        };
        assert!(matches!(result, Err(AnalystClientError::MalformedResponse)));
        server.join().unwrap();
    }
}
