use super::*;
use std::{
    io::{Read, Write},
    net::TcpListener,
    thread,
};

fn node(id: &str) -> serde_json::Value {
    serde_json::json!({"conceptId":id,"type":"project","title":id,"sourcePath":format!("{id}.md"),"sourceRevision":"reviewed-1","contentSha256":"b".repeat(64)})
}
fn graph() -> serde_json::Value {
    serde_json::json!({"schemaVersion":1,"generationSha256":"a".repeat(64),"permissionHash":"c".repeat(64),"authorizationHash":"d".repeat(64),"conceptId":"projects/yap","nodes":[node("projects/yap"),node("decisions/interface")],"hasMore":false,"relationships":[{"relationshipId":"e".repeat(64),"sourceConceptId":"decisions/interface","targetConceptId":"projects/yap","type":"supports","authority":"human_confirmed","citation":{"sourcePath":"decisions/interface.md","sourceRevision":"reviewed-1","contentSha256":"b".repeat(64),"charStart":null,"charEnd":null}}]})
}
fn request() -> ConnectionsRequest {
    ConnectionsRequest::Read {
        concept_id: "projects/yap".into(),
        generation_sha256: "a".repeat(64),
    }
}
fn decoded(value: &serde_json::Value) -> Result<ConnectionsResponse, ConnectionsError> {
    decode(&request(), &serde_json::to_vec(value).unwrap())
}

#[test]
fn exact_source_proof_and_canonical_authority_are_required() {
    assert!(decoded(&graph()).is_ok());
    for (key, value) in [
        ("authority", serde_json::json!("agent_proposed")),
        ("sourceConceptId", serde_json::json!("hidden/private")),
        ("relationshipId", serde_json::json!("bad")),
    ] {
        let mut wire = graph();
        wire["relationships"][0][key] = value;
        assert!(decoded(&wire).is_err());
    }
    for (key, value) in [
        ("sourcePath", serde_json::json!("other.md")),
        ("sourceRevision", serde_json::json!("old")),
        ("contentSha256", serde_json::json!("f".repeat(64))),
        ("charStart", serde_json::json!(1)),
        ("charEnd", serde_json::json!(1)),
    ] {
        let mut wire = graph();
        wire["relationships"][0]["citation"][key] = value;
        assert!(decoded(&wire).is_err());
    }
    for end in [1_000_001u64, 9_007_199_254_740_992] {
        let mut wire = graph();
        wire["relationships"][0]["citation"]["charStart"] = serde_json::json!(1);
        wire["relationships"][0]["citation"]["charEnd"] = serde_json::json!(end);
        assert!(decoded(&wire).is_err());
    }
    let mut wire = graph();
    wire["relationships"][0]["citation"]["charStart"] = serde_json::json!(2);
    wire["relationships"][0]["citation"]["charEnd"] = serde_json::json!(9);
    assert!(decoded(&wire).is_ok());
}
#[test]
fn context_identity_limits_and_unrelated_nodes_are_refused() {
    for (key, value) in [
        ("schemaVersion", serde_json::json!(2)),
        ("generationSha256", serde_json::json!("f".repeat(64))),
        ("conceptId", serde_json::json!("other")),
        ("permissionHash", serde_json::json!("bad")),
        ("hasMore", serde_json::json!(true)),
        ("ownerId", serde_json::json!("forged")),
    ] {
        let mut wire = graph();
        wire[key] = value;
        assert!(decoded(&wire).is_err());
    }
    let mut wire = graph();
    wire["nodes"]
        .as_array_mut()
        .unwrap()
        .push(node("unrelated"));
    assert!(decoded(&wire).is_err());
    let mut wire = graph();
    let duplicate = wire["nodes"][0].clone();
    wire["nodes"].as_array_mut().unwrap().push(duplicate);
    assert!(decoded(&wire).is_err());
    let mut wire = graph();
    let duplicate = wire["relationships"][0].clone();
    wire["relationships"]
        .as_array_mut()
        .unwrap()
        .push(duplicate);
    assert!(decoded(&wire).is_err());
    let mut wire = graph();
    wire["nodes"][0]["title"] = serde_json::json!("x".repeat(1025));
    assert!(decoded(&wire).is_err());
    assert!(decode(&request(), &vec![b' '; MAXIMUM_RESPONSE_BYTES + 1]).is_err());
}
#[test]
fn literal_topic_browse_and_isolated_topics_are_supported() {
    let browse = ConnectionsRequest::Browse {
        search: "Yap_%!".into(),
    };
    assert!(browse.is_valid());
    let mut page = graph();
    page.as_object_mut().unwrap().remove("conceptId");
    page.as_object_mut().unwrap().remove("relationships");
    assert!(decode(&browse, &serde_json::to_vec(&page).unwrap()).is_ok());
    page["nodes"] = serde_json::json!([]);
    assert!(decode(&browse, &serde_json::to_vec(&page).unwrap()).is_ok());
    page["hasMore"] = serde_json::json!(true);
    assert!(decode(&browse, &serde_json::to_vec(&page).unwrap()).is_err());
    let mut isolated = graph();
    isolated["nodes"] = serde_json::json!([node("projects/yap")]);
    isolated["relationships"] = serde_json::json!([]);
    assert!(decoded(&isolated).is_ok());
    for search in [" padded ".into(), "\0".into(), "x".repeat(129)] {
        assert!(!ConnectionsRequest::Browse { search }.is_valid());
    }
}
fn exchange(
    status: &str,
    body: String,
    size: Option<usize>,
    chunked: bool,
) -> (Result<ConnectionsResponse, ConnectionsError>, String) {
    exchange_request(&request(), status, body, size, chunked)
}
fn exchange_request(
    request: &ConnectionsRequest,
    status: &str,
    body: String,
    size: Option<usize>,
    chunked: bool,
) -> (Result<ConnectionsResponse, ConnectionsError>, String) {
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
            if incoming.windows(4).any(|w| w == b"\r\n\r\n") {
                break;
            }
        }
        if chunked {
            let _=write!(stream,"HTTP/1.1 {status}\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n{:x}\r\n{body}\r\n0\r\n\r\n",body.len());
        } else {
            let _=write!(stream,"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",size.unwrap_or(body.len()));
        }
        String::from_utf8(incoming).unwrap()
    });
    let client = ConnectionsClient::new(
        AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "private-token"),
        &format!("http://{address}"),
    )
    .unwrap();
    let result = tauri::async_runtime::block_on(client.execute(request));
    (result, server.join().unwrap())
}
#[test]
fn transport_owns_identity_and_cannot_accept_oversized_or_sensitive_error_text() {
    let (result, incoming) = exchange("200 OK", graph().to_string(), None, false);
    assert!(result.is_ok());
    assert!(incoming
        .starts_with("GET /v1/knowledge/connections?conceptId=projects%2Fyap&generationSha256="));
    assert!(incoming
        .to_lowercase()
        .contains("authorization: bearer private-token\r\n"));
    for (status, code) in [
        ("409 Conflict", "knowledgeChanged"),
        ("401 Unauthorized", "identityChanged"),
        ("403 Forbidden", "denied"),
        ("404 Not Found", "notFound"),
        ("429 Too Many Requests", "unavailable"),
    ] {
        let (result, _) = exchange(status, "private-corpus-or-credentials".into(), None, false);
        assert_eq!(result.unwrap_err().code, code);
    }
    assert_eq!(
        exchange(
            "200 OK",
            String::new(),
            Some(MAXIMUM_RESPONSE_BYTES + 1),
            false
        )
        .0
        .unwrap_err(),
        invalid()
    );
    assert_eq!(
        exchange("200 OK", "x".repeat(MAXIMUM_RESPONSE_BYTES + 1), None, true)
            .0
            .unwrap_err(),
        invalid()
    );
}

fn proposal_request() -> ConnectionsRequest {
    ConnectionsRequest::Proposal {
        proposal_id: "f".repeat(64),
    }
}
fn proposal_wire() -> serde_json::Value {
    let sources: Vec<_> = ["projects/yap", "decisions/interface"].into_iter().map(|id| serde_json::json!({
        "node":node(id),
        "citation":{"conceptId":id,"sourceRevision":"reviewed-1","contentSha256":"b".repeat(64),"charStart":12,"charEnd":18},
        "text":"Source"
    })).collect();
    serde_json::json!({"schemaVersion":1,"generationSha256":"a".repeat(64),"permissionHash":"c".repeat(64),"authorizationHash":"d".repeat(64),"proposalId":"f".repeat(64),"status":"proposed", "candidate":{"schemaVersion":1,"sourceConceptId":"projects/yap","targetConceptId":"decisions/interface","relationshipType":"supports","rationale":"The cited decision supports this project."},"sources":sources})
}
fn decoded_proposal(wire: &serde_json::Value) -> Result<ConnectionsResponse, ConnectionsError> {
    decode(&proposal_request(), &serde_json::to_vec(wire).unwrap())
}
#[test]
fn proposal_requires_requested_reference_and_unpublished_typed_candidate() {
    assert!(proposal_request().is_valid());
    assert!(decoded_proposal(&proposal_wire()).is_ok());
    for bad in ["", "F", "../source", &"a".repeat(63)] {
        assert!(!ConnectionsRequest::Proposal {
            proposal_id: bad.into()
        }
        .is_valid());
    }
    for (key, value) in [
        ("proposalId", serde_json::json!("a".repeat(64))),
        ("status", serde_json::json!("published")),
        ("schemaVersion", serde_json::json!(2)),
        ("generationSha256", serde_json::json!("old")),
        ("authority", serde_json::json!("human_confirmed")),
    ] {
        let mut wire = proposal_wire();
        wire[key] = value;
        assert!(decoded_proposal(&wire).is_err());
    }
    for (key, value) in [
        ("sourceConceptId", serde_json::json!("foreign")),
        ("targetConceptId", serde_json::json!("projects/yap")),
        ("relationshipType", serde_json::json!("has spaces")),
        ("rationale", serde_json::json!("\0")),
        ("rationale", serde_json::json!("界".repeat(2001))),
        ("canonical", serde_json::json!(true)),
    ] {
        let mut wire = proposal_wire();
        wire["candidate"][key] = value;
        assert!(decoded_proposal(&wire).is_err());
    }
}
#[test]
fn proposal_sources_must_match_exact_endpoint_identity_and_bounded_quote() {
    for (key, value) in [
        ("charStart", serde_json::json!(13)),
        ("charEnd", serde_json::json!(1_000_001)),
        ("sourceRevision", serde_json::json!("other")),
        ("contentSha256", serde_json::json!("e".repeat(64))),
        ("conceptId", serde_json::json!("decisions/interface")),
    ] {
        let mut wire = proposal_wire();
        wire["sources"][0]["citation"][key] = value;
        assert!(decoded_proposal(&wire).is_err());
    }
    let mut wire = proposal_wire();
    wire["sources"][1] = wire["sources"][0].clone();
    assert!(decoded_proposal(&wire).is_err());
    let mut wire = proposal_wire();
    wire["sources"].as_array_mut().unwrap().pop();
    assert!(decoded_proposal(&wire).is_err());
    for text in ["Source\0".to_owned(), "界".repeat(1025)] {
        let mut wire = proposal_wire();
        wire["sources"][0]["text"] = serde_json::json!(text);
        wire["sources"][0]["citation"]["charEnd"] = serde_json::json!(12 + text.chars().count());
        assert!(decoded_proposal(&wire).is_err());
    }
    // Citation offsets count Unicode scalar values, not UTF-8 bytes.
    let mut wire = proposal_wire();
    wire["sources"][0]["text"] = serde_json::json!("知識");
    wire["sources"][0]["citation"]["charEnd"] = serde_json::json!(14);
    assert!(decoded_proposal(&wire).is_ok());
}
#[test]
fn proposal_transport_sends_only_owned_reference_and_dispatcher_identity() {
    let (result, incoming) = exchange_request(
        &proposal_request(),
        "200 OK",
        proposal_wire().to_string(),
        None,
        false,
    );
    assert!(matches!(result, Ok(ConnectionsResponse::Proposal(_))));
    assert!(incoming.starts_with(&format!(
        "GET /v1/knowledge/connection-proposal?proposalId={} HTTP/1.1",
        "f".repeat(64)
    )));
    assert!(incoming
        .to_lowercase()
        .contains("authorization: bearer private-token\r\n"));
    assert!(!incoming.contains("conceptId=") && !incoming.contains("subject="));
}

#[test]
fn discard_uses_authenticated_delete_and_strict_reference_bound_receipt() {
    let request = ConnectionsRequest::Discard {
        proposal_id: "f".repeat(64),
    };
    let receipt = serde_json::json!({"schemaVersion":1,"proposalId":"f".repeat(64),
        "generationSha256":"a".repeat(64),"status":"discarded"});
    let (result, incoming) = exchange_request(&request, "200 OK", receipt.to_string(), None, false);
    assert!(matches!(result, Ok(ConnectionsResponse::Discarded(_))));
    assert!(incoming.starts_with(&format!(
        "DELETE /v1/knowledge/connection-proposal?proposalId={} HTTP/1.1",
        "f".repeat(64)
    )));
    assert!(incoming
        .to_lowercase()
        .contains("authorization: bearer private-token\r\n"));
    assert!(!incoming.contains("subjectId") && !incoming.contains("generationSha256="));
    for (field, value) in [
        ("proposalId", serde_json::json!("b".repeat(64))),
        ("status", serde_json::json!("proposed")),
        ("status", serde_json::json!("published")),
        ("generationSha256", serde_json::json!("invalid")),
        ("schemaVersion", serde_json::json!(2)),
        ("authority", serde_json::json!("human_confirmed")),
        ("sources", serde_json::json!([])),
    ] {
        let mut malformed = receipt.clone();
        malformed[field] = value;
        assert!(decode(&request, &serde_json::to_vec(&malformed).unwrap()).is_err());
    }
    assert!(
        serde_json::from_value::<ConnectionsRequest>(serde_json::json!({
            "action":"discard", "proposalId":"f".repeat(64), "subjectId":"forged"
        }))
        .is_err()
    );
}

#[test]
fn pending_discovery_uses_authenticated_get_without_identity_or_query_selectors() {
    let request = ConnectionsRequest::Pending {};
    let receipt = serde_json::json!({"schemaVersion":1,"proposals":[{
        "proposalId":"f".repeat(64),"createdAtUtc":"2026-10-03T12:00:00.123456Z"
    }]});
    let (result, incoming) = exchange_request(&request, "200 OK", receipt.to_string(), None, false);
    assert!(matches!(result, Ok(ConnectionsResponse::Pending(_))));
    assert!(incoming.starts_with("GET /v1/knowledge/connection-proposals HTTP/1.1"));
    assert!(incoming
        .to_lowercase()
        .contains("authorization: bearer private-token\r\n"));
    for field in [
        "subjectId",
        "tenantId",
        "proposalId",
        "limit",
        "generationSha256",
    ] {
        assert!(!incoming.contains(field));
        assert!(
            serde_json::from_value::<ConnectionsRequest>(serde_json::json!({
            "action":"pending", (field):"forged"
            }))
            .is_err()
        );
    }
}

#[test]
fn pending_discovery_refuses_corrupt_duplicate_excess_or_source_bearing_metadata() {
    let request = ConnectionsRequest::Pending {};
    let entry =
        serde_json::json!({"proposalId":"f".repeat(64),"createdAtUtc":"2026-10-03T12:00:00Z"});
    let receipt = serde_json::json!({"schemaVersion":1,"proposals":[entry]});
    assert!(decode(&request, br#"{"schemaVersion":1,"proposals":[]}"#).is_ok());
    for (field, value) in [
        ("proposalId", serde_json::json!("invalid")),
        ("createdAtUtc", serde_json::json!("2026-02-30T12:00:00Z")),
        (
            "createdAtUtc",
            serde_json::json!("2026-10-03T12:00:00+01:00"),
        ),
        ("createdAtUtc", serde_json::json!("infinity")),
        ("sources", serde_json::json!([])),
        ("subjectId", serde_json::json!("foreign")),
    ] {
        let mut malformed = receipt.clone();
        malformed["proposals"][0][field] = value;
        assert!(decode(&request, &serde_json::to_vec(&malformed).unwrap()).is_err());
    }
    for (field, value) in [
        ("schemaVersion", serde_json::json!(2)),
        ("hasMore", serde_json::json!(true)),
        ("generationSha256", serde_json::json!("a".repeat(64))),
    ] {
        let mut malformed = receipt.clone();
        malformed[field] = value;
        assert!(decode(&request, &serde_json::to_vec(&malformed).unwrap()).is_err());
    }
    let duplicate = serde_json::json!({"schemaVersion":1,"proposals":[entry,entry]});
    assert!(decode(&request, &serde_json::to_vec(&duplicate).unwrap()).is_err());
    let mut full = serde_json::json!({"schemaVersion":1,"proposals":[]});
    for index in 0..64 {
        full["proposals"]
            .as_array_mut()
            .unwrap()
            .push(serde_json::json!({
                "proposalId":format!("{index:064x}"),"createdAtUtc":"2026-10-03T12:00:00Z"
            }));
    }
    assert!(decode(&request, &serde_json::to_vec(&full).unwrap()).is_ok());
    full["proposals"].as_array_mut().unwrap().push(entry);
    assert!(decode(&request, &serde_json::to_vec(&full).unwrap()).is_err());
}

#[test]
fn review_package_preserves_exact_evidence_without_session_or_approval_metadata() {
    let mut wire = proposal_wire();
    wire["sources"][0]["text"] = serde_json::json!("知識🦀");
    wire["sources"][0]["citation"]["charEnd"] = serde_json::json!(15);
    let ConnectionsResponse::Proposal(proposal) = decoded_proposal(&wire).unwrap() else {
        panic!("expected strictly decoded proposal");
    };
    let package = proposal.review_package(&"a".repeat(64)).unwrap();
    assert!(package.ends_with('\n'));
    assert!(package.len() <= MAXIMUM_RESPONSE_BYTES);
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&package).unwrap(),
        serde_json::json!({
            "schemaVersion":1, "kind":"connection-review", "status":"proposed",
            "proposalId":wire["proposalId"], "generationSha256":wire["generationSha256"],
            "candidate":wire["candidate"], "sources":wire["sources"]
        })
    );
    for generation in ["f".repeat(64), "invalid".into(), "A".repeat(64)] {
        assert_eq!(
            proposal.review_package(&generation).unwrap_err().code,
            "knowledgeChanged"
        );
    }
}
