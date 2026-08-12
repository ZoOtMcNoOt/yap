use std::{
    io::{Read, Write},
    net::TcpListener,
    thread,
};

use super::*;

fn sha(character: char) -> String {
    character.to_string().repeat(64)
}

fn request() -> TranscriptCorrectionRequest {
    let text = "Um, the dosage is 25 mg.";
    TranscriptCorrectionRequest::new(
        sha('a'),
        sha256_text(text),
        vec![TranscriptCorrectionSegment::new(
            "segment-0001".into(),
            0,
            24,
            0,
            1_500,
            "en-US".into(),
            text.into(),
            sha256_text(text),
        )
        .unwrap()],
    )
    .unwrap()
}

#[test]
fn request_owns_only_exact_finalized_segments() {
    let value = serde_json::to_value(request()).unwrap();
    assert_eq!(
        value,
        serde_json::json!({
            "schemaVersion": 1,
            "sourceRevisionSha256": sha('a'),
            "sourceSha256": sha256_text("Um, the dosage is 25 mg."),
            "segments": [{
                "segmentId": "segment-0001",
                "startCharacter": 0,
                "endCharacter": 24,
            "startMilliseconds": 0,
            "endMilliseconds": 1500,
                "languageBcp47": "en-US",
                "text": "Um, the dosage is 25 mg.",
                "textSha256": sha256_text("Um, the dosage is 25 mg.")
            }]
        })
    );

    assert!(TranscriptCorrectionRequest::new(sha('a'), sha('b'), request().segments).is_err());
}

#[test]
fn finalized_source_builder_preserves_unicode_segments_timing_and_all_hashes() {
    let first = "a".repeat(MAXIMUM_SEGMENT_CHARACTERS - 2);
    let second = " é";
    let source = format!("{first}{second}");
    let request = TranscriptCorrectionRequest::from_finalized_segments(
        sha('a'),
        vec![
            TranscriptCorrectionSegment::new(
                "segment-0001".into(),
                0,
                first.chars().count(),
                0,
                1_000,
                "en-US".into(),
                first.clone(),
                sha256_text(&first),
            )
            .unwrap(),
            TranscriptCorrectionSegment::new(
                "segment-0002".into(),
                first.chars().count(),
                source.chars().count(),
                1_000,
                1_200,
                "en-US".into(),
                second.into(),
                sha256_text(second),
            )
            .unwrap(),
        ],
    )
    .unwrap();
    let value = serde_json::to_value(&request).unwrap();
    assert_eq!(value["sourceSha256"], sha256_text(&source));
    assert_eq!(value["segments"].as_array().unwrap().len(), 2);
    assert_eq!(value["segments"][0]["startCharacter"], 0);
    assert_eq!(
        value["segments"][0]["endCharacter"],
        MAXIMUM_SEGMENT_CHARACTERS - 2
    );
    assert_eq!(
        value["segments"][1]["startCharacter"],
        MAXIMUM_SEGMENT_CHARACTERS - 2
    );
    assert_eq!(
        value["segments"][1]["endCharacter"],
        MAXIMUM_SEGMENT_CHARACTERS
    );
    assert_eq!(value["segments"][1]["text"], " é");
    assert_eq!(value["segments"][1]["textSha256"], sha256_text(" é"));
    assert_eq!(value["segments"][1]["startMilliseconds"], 1_000);
}

#[test]
fn request_rejects_caller_claimed_hashes_that_do_not_match_source_bytes() {
    let mut segment = request().segments.into_iter().next().unwrap();
    segment.text_sha256 = sha('0');
    assert!(TranscriptCorrectionRequest::new(sha('a'), sha('b'), vec![segment],).is_err());

    let request = TranscriptCorrectionRequest::from_finalized_segments(
        sha('a'),
        vec![TranscriptCorrectionSegment::new(
            "segment-0001".into(),
            0,
            6,
            0,
            1,
            "und".into(),
            "source".into(),
            sha256_text("source"),
        )
        .unwrap()],
    )
    .unwrap();
    assert_eq!(request.source_sha256, sha256_text("source"));
}

#[test]
fn authenticated_client_submits_and_decodes_one_bounded_job_view() {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut request_bytes = Vec::new();
        let mut headers = [0_u8; 4096];
        let count = stream.read(&mut headers).unwrap();
        request_bytes.extend_from_slice(&headers[..count]);
        let request_text = String::from_utf8_lossy(&request_bytes);
        assert!(request_text.starts_with("POST /v1/transcript-corrections HTTP/1.1\r\n"));
        assert!(request_text
            .to_ascii_lowercase()
            .contains("authorization: bearer private-token"));
        let body = serde_json::json!({
            "schemaVersion": 1,
            "requestId": "agent-0123456789abcdef0123456789abcdef",
            "status": "queued",
            "sourceRevisionSha256": sha('a'),
            "sourceSha256": sha('b'),
            "terminologySnapshotSha256": sha('c'),
            "applied": false
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

    let client = TranscriptCorrectionApiClient::new(
        AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "private-token"),
        &format!("http://{address}"),
    )
    .unwrap();
    let view = tauri::async_runtime::block_on(client.submit(&request())).unwrap();
    assert_eq!(view.status, TranscriptCorrectionStatus::Queued);
    assert_eq!(view.source_revision_sha256, sha('a'));
    assert!(!view.applied);
    server.join().unwrap();
}

#[test]
fn response_status_shape_and_source_identity_fail_closed() {
    let base = serde_json::json!({
        "schemaVersion": 1,
        "requestId": "agent-0123456789abcdef0123456789abcdef",
        "status": "complete",
        "sourceRevisionSha256": sha('a'),
        "sourceSha256": sha('b'),
        "terminologySnapshotSha256": sha('c'),
        "applied": true,
        "correctedText": "The dosage is 25 mg."
    });
    let view = decode_job_view(serde_json::to_vec(&base).unwrap()).unwrap();
    assert_eq!(view.status, TranscriptCorrectionStatus::Complete);
    assert!(view.applied);

    let mut malformed = base.clone();
    malformed["status"] = serde_json::json!("queued");
    assert!(decode_job_view(serde_json::to_vec(&malformed).unwrap()).is_err());

    let mut malformed = base;
    malformed["sourceSha256"] = serde_json::json!("UPPER");
    assert!(decode_job_view(serde_json::to_vec(&malformed).unwrap()).is_err());
}
