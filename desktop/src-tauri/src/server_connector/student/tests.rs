use std::{
    io::{Read, Write},
    net::TcpListener,
    thread,
};

use super::*;

fn sha(character: char) -> String {
    character.to_string().repeat(64)
}

fn request() -> StudentRequest {
    StudentRequest::new("meetings/job-1".into(), sha('a'), "crash safety".into()).unwrap()
}

fn complete_view() -> serde_json::Value {
    serde_json::json!({
        "schemaVersion": 1,
        "requestId": format!("student-question-{}", "1".repeat(32)),
        "status": "complete",
        "conversationConceptId": "meetings/job-1",
        "generationSha256": sha('a'),
        "evidenceSha256": sha('d'),
        "questions": [{
            "schemaVersion": 3,
            "sourceSubject": "crash safety",
            "question": "What should you remember about crash safety?",
            "sourceSupports": [{
                "sourceCitation": {
                    "conceptId": "meetings/job-1",
                    "sourceRevision": sha('b'),
                    "contentSha256": sha('c'),
                    "charStart": 0,
                    "charEnd": 44
                },
                "supportQuote": "crash safety",
                "supportCharStart": 29,
                "supportCharEnd": 41
            }]
        }],
        "outputBudgetExhausted": false
    })
}

#[test]
fn request_owns_only_exact_meeting_generation_and_topic() {
    assert_eq!(
        serde_json::to_value(request()).unwrap(),
        serde_json::json!({
            "schemaVersion": 2,
            "conversationConceptId": "meetings/job-1",
            "expectedGenerationSha256": sha('a'),
            "topic": "crash safety"
        })
    );
    assert!(StudentRequest::new("other/job-1".into(), sha('a'), "topic".into()).is_err());
    assert!(StudentRequest::new("meetings/job-1".into(), sha('A'), "topic".into()).is_err());
    assert!(StudentRequest::new("meetings/job-1".into(), sha('a'), " question?".into()).is_err());
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
        assert!(request_text.starts_with("POST /v1/student-questions HTTP/1.1\r\n"));
        assert!(request_text
            .to_ascii_lowercase()
            .contains("authorization: bearer private-token"));
        let body = serde_json::json!({
            "schemaVersion": 1,
            "requestId": format!("student-question-{}", "1".repeat(32)),
            "status": "queued",
            "conversationConceptId": "meetings/job-1",
            "generationSha256": sha('a'),
            "questions": [],
            "outputBudgetExhausted": false
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

    let client = StudentApiClient::new(
        AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "private-token"),
        &format!("http://{address}"),
    )
    .unwrap();
    let view = tauri::async_runtime::block_on(client.submit(&request())).unwrap();
    assert_eq!(view.status, StudentQuestionStatus::Queued);
    server.join().unwrap();
}

#[test]
fn complete_question_and_source_identity_fail_closed() {
    let view = decode_job_view(serde_json::to_vec(&complete_view()).unwrap()).unwrap();
    assert_eq!(view.status, StudentQuestionStatus::Complete);
    assert_eq!(view.questions.len(), 1);
    assert!(view.matches_request(&request()));

    let mut malformed = complete_view();
    malformed["generationSha256"] = serde_json::json!(sha('f'));
    assert!(!decode_job_view(serde_json::to_vec(&malformed).unwrap())
        .unwrap()
        .matches_request(&request()));

    let mut malformed = complete_view();
    malformed["questions"][0]["question"] = serde_json::json!("Invented question?");
    assert!(decode_job_view(serde_json::to_vec(&malformed).unwrap()).is_err());

    let mut malformed = complete_view();
    malformed["questions"][0]["sourceSupports"][0]["supportCharEnd"] = serde_json::json!(42);
    assert!(decode_job_view(serde_json::to_vec(&malformed).unwrap()).is_err());

    let mut malformed = complete_view();
    malformed["status"] = serde_json::json!("running");
    assert!(decode_job_view(serde_json::to_vec(&malformed).unwrap()).is_err());
}
