use super::*;
use serde_json::json;
fn generation() -> Value {
    json!({"schemaVersion":1,"generationSha256":"a".repeat(64),"sourceRevision":"reviewed-1","status":"staged","activeGenerationSha256":null,"conceptCount":2,"chunkCount":2,"relationshipCount":1,"permissionCount":2})
}
fn inspect() -> RebuildRequest {
    RebuildRequest::Inspect {
        generation_sha256: "a".repeat(64),
    }
}
#[test]
fn rebuild_receipts_require_exact_fields_nullable_context_and_target() {
    let wire = generation();
    assert!(decode(&inspect(), &serde_json::to_vec(&wire).unwrap()).is_ok());
    for (key, value) in [
        ("schemaVersion", json!(2)),
        ("generationSha256", json!("b".repeat(64))),
        ("chunkCount", json!(1.5)),
        ("permissionCount", json!(true)),
        ("conceptCount", json!(1_000_001)),
        ("sourceRevision", json!("\nprivate")),
        ("status", json!("active")),
        ("approval", json!(true)),
    ] {
        let mut changed = wire.clone();
        changed[key] = value;
        assert!(
            decode(&inspect(), &serde_json::to_vec(&changed).unwrap()).is_err(),
            "{key}"
        );
    }
    let mut missing = wire.clone();
    missing
        .as_object_mut()
        .unwrap()
        .remove("activeGenerationSha256");
    assert!(decode(&inspect(), &serde_json::to_vec(&missing).unwrap()).is_err());
    let duplicate = wire.to_string().replacen("{", "{\"schemaVersion\":9,", 1);
    assert!(decode(&inspect(), duplicate.as_bytes()).is_err());
    assert!(decode(&inspect(), &vec![b' '; 65_537]).is_err());
}
#[test]
fn activation_replay_confirms_a_lost_reply_without_requiring_the_old_active_value() {
    let request = RebuildRequest::Publish {
        generation_sha256: "a".repeat(64),
        expected_active_generation_sha256: Some("b".repeat(64)),
    };
    let mut wire = generation();
    wire["status"] = json!("active");
    wire["activeGenerationSha256"] = json!("a".repeat(64));
    wire["changed"] = json!(true);
    wire["previousActiveGenerationSha256"] = json!("b".repeat(64));
    assert!(decode(&request, &serde_json::to_vec(&wire).unwrap()).is_ok());
    wire["previousActiveGenerationSha256"] = Value::Null;
    assert!(decode(&request, &serde_json::to_vec(&wire).unwrap()).is_err());
    wire["changed"] = json!(false);
    wire["previousActiveGenerationSha256"] = json!("a".repeat(64));
    assert!(decode(&request, &serde_json::to_vec(&wire).unwrap()).is_ok());
    wire.as_object_mut()
        .unwrap()
        .remove("previousActiveGenerationSha256");
    assert!(decode(&request, &serde_json::to_vec(&wire).unwrap()).is_err());
}
#[test]
fn source_and_embedding_receipts_are_distinct_from_generation_completeness() {
    let mut source = generation();
    source["sourcePath"] = json!("reviewed/organization");
    source["status"] = json!("unadmitted");
    assert!(decode(
        &RebuildRequest::Source {},
        &serde_json::to_vec(&source).unwrap()
    )
    .is_ok());
    source["changed"] = json!(true);
    assert!(
        decode(
            &RebuildRequest::Stage {
                generation_sha256: "a".repeat(64)
            },
            &serde_json::to_vec(&source).unwrap()
        )
        .is_err(),
        "staging cannot confirm an unadmitted source"
    );
    assert!(decode(
        &RebuildRequest::Source {},
        &serde_json::to_vec(&source).unwrap()
    )
    .is_err());
    let embedding = json!({"schemaVersion":1,"generationSha256":"a".repeat(64),"status":"prepared","chunkCount":2,"embeddingModelId":"reviewed-embedding","embeddingModelRevision":"f".repeat(64),"changed":false});
    let request = RebuildRequest::Embeddings {
        generation_sha256: "a".repeat(64),
    };
    assert!(decode(&request, &serde_json::to_vec(&embedding).unwrap()).is_ok());
    for model in ["", "model with spaces", "model\ncredentials"] {
        let mut bad = embedding.clone();
        bad["embeddingModelId"] = json!(model);
        assert!(decode(&request, &serde_json::to_vec(&bad).unwrap()).is_err());
    }
}

fn exchange(
    request: &RebuildRequest,
    status: &str,
    body: &str,
) -> (Result<RebuildResponse, RebuildError>, String) {
    use std::{
        io::{Read, Write},
        net::TcpListener,
    };
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    let status = status.to_owned();
    let body = body.to_owned();
    let worker = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(std::time::Duration::from_secs(2)))
            .unwrap();
        let mut incoming = Vec::new();
        let mut chunk = [0u8; 4096];
        loop {
            let n = stream.read(&mut chunk).unwrap();
            assert!(n > 0);
            incoming.extend_from_slice(&chunk[..n]);
            if let Some(end) = incoming.windows(4).position(|v| v == b"\r\n\r\n") {
                let headers = String::from_utf8_lossy(&incoming[..end]);
                let length = headers
                    .lines()
                    .find_map(|l| {
                        l.to_ascii_lowercase()
                            .strip_prefix("content-length: ")
                            .and_then(|v| v.parse::<usize>().ok())
                    })
                    .unwrap_or(0);
                if incoming.len() >= end + 4 + length {
                    break;
                }
            }
        }
        if status == "DROP" {
            return String::from_utf8(incoming).unwrap();
        }
        write!(stream,"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).unwrap();
        String::from_utf8(incoming).unwrap()
    });
    let client = RebuildClient::new(
        AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "fixture-private-bearer"),
        &origin,
    )
    .unwrap();
    let result = tauri::async_runtime::block_on(client.execute(request));
    (result, worker.join().unwrap())
}
#[test]
fn native_rebuild_transport_owns_routes_bearer_and_exact_mutation_body() {
    let (result, incoming) = exchange(&inspect(), "200 OK", &generation().to_string());
    assert!(result.is_ok());
    assert!(incoming.starts_with(&format!(
        "GET /v1/knowledge/publications?generationSha256={}",
        "a".repeat(64)
    )));
    assert!(incoming
        .to_lowercase()
        .contains("authorization: bearer fixture-private-bearer\r\n"));
    let mut source = generation();
    source["sourcePath"] = json!("reviewed/source");
    source["changed"] = json!(true);
    let request = RebuildRequest::Stage {
        generation_sha256: "a".repeat(64),
    };
    let (result, incoming) = exchange(&request, "200 OK", &source.to_string());
    assert!(result.is_ok());
    assert!(incoming.starts_with("POST /v1/knowledge/source-preparations "));
    let payload: Value = serde_json::from_str(incoming.split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(
        payload,
        json!({"schemaVersion":1,"expectedGenerationSha256":"a".repeat(64)})
    );
}
#[test]
fn malformed_or_lost_write_replies_are_unconfirmed_and_private_errors_are_redacted() {
    let request = RebuildRequest::Publish {
        generation_sha256: "a".repeat(64),
        expected_active_generation_sha256: None,
    };
    for (status, body, code, unconfirmed) in [
        ("DROP", "", "unavailable", true),
        (
            "200 OK",
            "private credential and source",
            "invalidResponse",
            true,
        ),
        (
            "503 Service Unavailable",
            "private source",
            "unavailable",
            true,
        ),
        ("409 Conflict", "private source", "knowledgeChanged", false),
        ("403 Forbidden", "private source", "denied", false),
        ("404 Not Found", "private source", "notFound", false),
    ] {
        let (result, _) = exchange(&request, status, body);
        let error = result.unwrap_err();
        assert_eq!(error.code, code);
        assert_eq!(error.unconfirmed, unconfirmed);
        assert!(!serde_json::to_string(&error).unwrap().contains("private"));
    }
}
#[test]
fn renderer_request_cannot_supply_routing_identity_models_or_omit_nullable_expectation() {
    for wire in [
        json!({"action":"source","endpoint":"https://other.example"}),
        json!({"action":"publish","generationSha256":"a".repeat(64)}),
        json!({"action":"embeddings","generationSha256":"a".repeat(64),"model":"secret"}),
    ] {
        assert!(serde_json::from_value::<RebuildRequest>(wire).is_err());
    }
    let request:RebuildRequest=serde_json::from_value(json!({"action":"publish","generationSha256":"a".repeat(64),"expectedActiveGenerationSha256":null})).unwrap();
    assert!(request.valid());
}
#[test]
#[ignore = "requires the owned real HTTP/PostgreSQL rebuild fixture; run verification/run-native-knowledge-rebuild.py"]
fn native_real_postgres_rebuild_journey() {
    let origin = std::env::var("YAP_REBUILD_TEST_ORIGIN").expect("owned fixture origin");
    let target = std::env::var("YAP_REBUILD_TEST_TARGET").expect("owned fixture target");
    let base = std::env::var("YAP_REBUILD_TEST_BASE").expect("owned fixture retained base");
    let client = RebuildClient::new(
        AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "alice"),
        &origin,
    )
    .unwrap();
    tauri::async_runtime::block_on(async {
        let health_bytes = reqwest::Client::new()
            .get(format!("{origin}/v1/health"))
            .send()
            .await
            .unwrap()
            .error_for_status()
            .unwrap()
            .bytes()
            .await
            .unwrap();
        let health: Value = serde_json::from_slice(&health_bytes).unwrap();
        assert_eq!(health["capabilities"]["knowledgeRebuild"], true);
        let source = client.execute(&RebuildRequest::Source {}).await.unwrap();
        assert_eq!(source.value["generationSha256"], target);
        assert_eq!(source.value["activeGenerationSha256"], base);
        let staged = client
            .execute(&RebuildRequest::Stage {
                generation_sha256: target.clone(),
            })
            .await
            .unwrap();
        assert_eq!(staged.value["status"], "staged");
        let preparation = RebuildRequest::Embeddings {
            generation_sha256: target.clone(),
        };
        assert_eq!(
            client.execute(&preparation).await.unwrap().value["changed"],
            true
        );
        assert_eq!(
            client.execute(&preparation).await.unwrap().value["changed"],
            false
        );
        let inspected = client
            .execute(&RebuildRequest::Inspect {
                generation_sha256: target.clone(),
            })
            .await
            .unwrap();
        assert_eq!(inspected.value["status"], "staged");
        let publish = RebuildRequest::Publish {
            generation_sha256: target.clone(),
            expected_active_generation_sha256: Some(base.clone()),
        };
        let active = client.execute(&publish).await.unwrap();
        assert_eq!(active.value["status"], "active");
        assert_eq!(active.value["previousActiveGenerationSha256"], base);
        assert_eq!(
            client.execute(&publish).await.unwrap().value["changed"],
            false
        );
        let reader = crate::server_connector::knowledge_connections::ConnectionsClient::new(
            AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "alice"),
            &origin,
        )
        .unwrap();
        let browse = crate::server_connector::knowledge_connections::ConnectionsRequest::Browse {
            search: String::new(),
        };
        let topics = serde_json::to_value(reader.execute(&browse).await.unwrap()).unwrap();
        assert_eq!(topics["value"]["generationSha256"], target);
        assert!(!topics["value"]["nodes"].as_array().unwrap().is_empty());
        let foreign_reader =
            crate::server_connector::knowledge_connections::ConnectionsClient::new(
                AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "bob"),
                &origin,
            )
            .unwrap();
        let hidden = serde_json::to_value(foreign_reader.execute(&browse).await.unwrap()).unwrap();
        assert!(hidden["value"]["nodes"].as_array().unwrap().is_empty());
        let retained = client
            .execute(&RebuildRequest::Inspect {
                generation_sha256: base.clone(),
            })
            .await
            .unwrap();
        assert_eq!(retained.value["status"], "retained");
        let restored = client
            .execute(&RebuildRequest::Restore {
                generation_sha256: base.clone(),
                expected_active_generation_sha256: Some(target),
            })
            .await
            .unwrap();
        assert_eq!(restored.value["generationSha256"], base);
        assert_eq!(restored.value["changed"], true);
        let foreign = RebuildClient::new(
            AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "bob"),
            &origin,
        )
        .unwrap();
        assert_eq!(
            foreign
                .execute(&RebuildRequest::Inspect {
                    generation_sha256: base
                })
                .await
                .unwrap_err()
                .code,
            "notFound"
        );
    });
}
