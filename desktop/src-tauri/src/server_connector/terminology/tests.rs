use super::*;
use std::{
    io::{Read, Write},
    net::TcpListener,
    thread,
};

fn record() -> serde_json::Value {
    serde_json::json!({"scopeId":"personal","recordId":"term-1","locale":"en-US","canonicalForm":"Yap","variants":["yapp"],"sensitivity":"internal","version":1,"changedAt":"2026-10-02T12:00:00Z"})
}
fn request(action: &str) -> TerminologyRequest {
    serde_json::from_value(match action {
        "list" => serde_json::json!({"scopeId":"personal","action":"list","locale":"en-US","after":null}),
        "create" => serde_json::json!({"scopeId":"personal","action":"create","mutationId":"11111111-1111-4111-8111-111111111111","locale":"en-US","canonicalForm":"Yap","variants":["yapp"],"sensitivity":"internal"}),
        "edit" => serde_json::json!({"scopeId":"personal","action":"edit","recordId":"term-1","expectedVersion":1,"canonicalForm":"Yap","variants":["yapp"],"sensitivity":"internal"}),
        _ => serde_json::json!({"scopeId":"personal","action":"delete","recordId":"term-1","expectedVersion":1}),
    }).unwrap()
}

#[test]
fn responses_must_match_request_identity_content_version_and_locale() {
    let wire = serde_json::to_vec(&record()).unwrap();
    assert!(decode_response(&request("create"), StatusCode::CREATED, &wire).is_ok());
    assert!(decode_response(&request("create"), StatusCode::OK, &wire).is_err());
    for (key, value) in [
        ("canonicalForm", serde_json::json!("other")),
        ("version", serde_json::json!(2)),
        ("locale", serde_json::json!("de-DE")),
        ("scopeId", serde_json::json!("team:clinical")),
        ("ownerId", serde_json::json!("forged")),
    ] {
        let mut value_record = record();
        value_record[key] = value;
        assert!(decode_response(
            &request("create"),
            StatusCode::CREATED,
            &serde_json::to_vec(&value_record).unwrap()
        )
        .is_err());
    }
    let mut edited = record();
    edited["version"] = serde_json::json!(2);
    assert!(decode_response(
        &request("edit"),
        StatusCode::OK,
        &serde_json::to_vec(&edited).unwrap()
    )
    .is_ok());
    edited["recordId"] = serde_json::json!("term-other");
    assert!(decode_response(
        &request("edit"),
        StatusCode::OK,
        &serde_json::to_vec(&edited).unwrap()
    )
    .is_err());
    let deleted =
        serde_json::json!({"scopeId":"personal","recordId":"term-1","version":2,"deleted":true});
    assert!(decode_response(
        &request("delete"),
        StatusCode::OK,
        &serde_json::to_vec(&deleted).unwrap()
    )
    .is_ok());
}

#[test]
fn shared_receipts_cannot_retarget_another_scope_even_with_the_same_record_id() {
    let scoped: TerminologyRequest = serde_json::from_value(serde_json::json!({
        "action":"edit","scopeId":"team:clinical","recordId":"term-1","expectedVersion":1,
        "canonicalForm":"Yap","variants":["yapp"],"sensitivity":"internal"
    }))
    .unwrap();
    let mut receipt = record();
    receipt["version"] = serde_json::json!(2);
    assert!(decode_response(
        &scoped,
        StatusCode::OK,
        &serde_json::to_vec(&receipt).unwrap()
    )
    .is_err());
    receipt["scopeId"] = serde_json::json!("team:clinical");
    assert!(decode_response(
        &scoped,
        StatusCode::OK,
        &serde_json::to_vec(&receipt).unwrap()
    )
    .is_ok());
    for scope in ["team:research", "organization", "personal"] {
        receipt["scopeId"] = serde_json::json!(scope);
        assert!(decode_response(
            &scoped,
            StatusCode::OK,
            &serde_json::to_vec(&receipt).unwrap()
        )
        .is_err());
    }
}

#[test]
fn discovery_requires_bounded_unique_scopes_and_readable_labels_with_consistent_kinds() {
    let request: TerminologyRequest =
        serde_json::from_value(serde_json::json!({"action":"discover"})).unwrap();
    let personal = serde_json::json!({"scopeId":"personal","kind":"personal","label":"Personal","canManage":true});
    let team = serde_json::json!({"scopeId":"team:clinical","kind":"team","label":"Clinical team","canManage":false});
    let valid = serde_json::json!({"scopes":[personal.clone(),team.clone()]});
    assert!(decode_response(
        &request,
        StatusCode::OK,
        &serde_json::to_vec(&valid).unwrap()
    )
    .is_ok());
    for bad in [
        serde_json::json!({"scopes":[]}),
        serde_json::json!({"scopes":[team.clone()]}),
        serde_json::json!({"scopes":[personal.clone(),team.clone(),team.clone()]}),
        serde_json::json!({"scopes":vec![personal.clone();35]}),
    ] {
        assert!(
            decode_response(&request, StatusCode::OK, &serde_json::to_vec(&bad).unwrap()).is_err()
        );
    }
    for (field, value) in [
        ("kind", serde_json::json!("organization")),
        ("label", serde_json::json!("private\nlabel")),
        ("label", serde_json::json!("x".repeat(129))),
        ("ownerId", serde_json::json!("forged")),
    ] {
        let mut bad = valid.clone();
        bad["scopes"][1][field] = value;
        assert!(
            decode_response(&request, StatusCode::OK, &serde_json::to_vec(&bad).unwrap()).is_err()
        );
    }
    for scope in [
        "team:../other",
        "team:",
        "owner:alice",
        "team:clinical?role=admin",
    ] {
        assert!(!valid_scope(scope));
    }
}

#[test]
fn paging_rejects_wrong_locale_duplicate_ids_and_forged_cursor() {
    let valid = serde_json::json!({"scopeId":"personal","records":[record()],"nextCursor":null});
    assert!(decode_response(
        &request("list"),
        StatusCode::OK,
        &serde_json::to_vec(&valid).unwrap()
    )
    .is_ok());
    for invalid_page in [
        serde_json::json!({"scopeId":"personal","records":[record(),record()],"nextCursor":null}),
        serde_json::json!({"scopeId":"personal","records":[record()],"nextCursor":"term-other"}),
    ] {
        assert!(decode_response(
            &request("list"),
            StatusCode::OK,
            &serde_json::to_vec(&invalid_page).unwrap()
        )
        .is_err());
    }
    let mut invalid_page = valid;
    invalid_page["records"][0]["locale"] = serde_json::json!("de-DE");
    assert!(decode_response(
        &request("list"),
        StatusCode::OK,
        &serde_json::to_vec(&invalid_page).unwrap()
    )
    .is_err());
}

#[test]
fn requests_reject_forged_authority_paths_and_unbounded_content() {
    assert!(serde_json::from_value::<TerminologyRequest>(
        serde_json::json!({"action":"discover","ownerId":"forged"})
    )
    .is_err());
    assert!(serde_json::from_value::<TerminologyRequest>(
        serde_json::json!({"scopeId":"personal","action":"list","locale":"en-US","ownerId":"forged"})
    )
    .is_err());
    for locale in ["EN-us", "en-US-GB", "en-Latn-US-GB", "", "en?owner=x"] {
        assert!(!valid_locale(locale));
    }
    for locale in ["und", "en", "en-US", "zh-Hant-TW", "es-419"] {
        assert!(valid_locale(locale));
    }
    assert!(!valid_id("../foreign"));
    assert!(!valid_id("term?owner=other"));
    assert!(!valid_content("Yap", &["x".repeat(513)]));
    assert!(!valid_content("Yap", &[]));
    assert!(!valid_form("Yap\nsecret"));
    assert!(!valid_version(0));
    assert!(!valid_version(i64::MAX as u64));
}

fn exchange(
    status: &str,
    response: String,
    announced_size: Option<usize>,
) -> (Result<TerminologyResponse, TerminologyError>, String) {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let status = status.to_owned();
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut incoming = Vec::new();
        let mut chunk = [0u8; 4096];
        loop {
            let count = stream.read(&mut chunk).unwrap();
            if count == 0 {
                break;
            }
            incoming.extend_from_slice(&chunk[..count]);
            if let Some(end) = incoming.windows(4).position(|w| w == b"\r\n\r\n") {
                let headers = String::from_utf8_lossy(&incoming[..end]).to_ascii_lowercase();
                let length: usize = headers
                    .lines()
                    .find_map(|l| {
                        l.strip_prefix("content-length: ")
                            .and_then(|v| v.parse().ok())
                    })
                    .unwrap_or(0);
                if incoming.len() >= end + 4 + length {
                    break;
                }
            }
        }
        write!(stream, "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{response}", announced_size.unwrap_or(response.len())).unwrap();
        String::from_utf8(incoming).unwrap()
    });
    let client = TerminologyClient::new(
        AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "private-token"),
        &format!("http://{address}"),
    )
    .unwrap();
    let result = tauri::async_runtime::block_on(client.execute(&request("create")));
    (result, server.join().unwrap())
}

#[test]
fn native_transport_owns_authorization_and_sends_only_vocabulary_fields() {
    let (result, incoming) = exchange("201 Created", record().to_string(), None);
    assert!(result.is_ok());
    assert!(incoming.starts_with("POST /v1/terminology?scopeId=personal HTTP/1.1\r\n"));
    assert!(incoming
        .to_ascii_lowercase()
        .contains("authorization: bearer private-token\r\n"));
    let body: serde_json::Value =
        serde_json::from_str(incoming.split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(body.as_object().unwrap().len(), 5);
    assert_eq!(body["mutationId"], "11111111-1111-4111-8111-111111111111");
    assert!(body.get("action").is_none());
    assert!(body.get("ownerId").is_none());
}

#[test]
fn conflicts_and_oversized_responses_return_constant_errors_without_server_text() {
    let (result, _) = exchange(
        "409 Conflict",
        "private-content-and-credentials".into(),
        None,
    );
    assert_eq!(
        result.unwrap_err(),
        TerminologyError::new("conflict", false)
    );
    let (result, _) = exchange(
        "201 Created",
        String::new(),
        Some(MAXIMUM_RESPONSE_BYTES + 1),
    );
    assert_eq!(
        result.unwrap_err(),
        TerminologyError::new("invalidResponse", false)
    );
}
