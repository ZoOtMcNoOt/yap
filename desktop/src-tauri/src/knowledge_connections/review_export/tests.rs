use super::*;
use crate::server_connector::AuthenticatedRequestDispatcher;
use std::{
    io::{Read, Write},
    net::TcpListener,
    path::PathBuf,
    thread,
};

struct Fixture {
    root: PathBuf,
    data: PathBuf,
    output: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        static SEQUENCE: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "yap-review-export-{}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos(),
            SEQUENCE.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
        ));
        let data = root.join("data");
        let output = root.join("exports");
        std::fs::create_dir_all(&data).unwrap();
        std::fs::create_dir(&output).unwrap();
        Self { root, data, output }
    }
    fn publish(&self, target: &Path) -> Result<ReviewExport, ConnectionsError> {
        publish_package(
            "{\"evidence\":\"知識🦀\"}\n",
            "{\"evidence\":\"知識🦀\"}\n",
            target,
            &self.data,
        )
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.root).ok();
    }
}

#[test]
fn new_json_export_is_exact_utf8_and_supplies_only_the_missing_extension() {
    let fixture = Fixture::new();
    for name in ["review", "uppercase.JSON"] {
        let selected = fixture.output.join(name);
        let destination = if selected.extension().is_none() {
            selected.with_extension("json")
        } else {
            selected.clone()
        };
        assert_eq!(
            fixture.publish(&selected).unwrap(),
            ReviewExport::Saved {
                path: destination
                    .canonicalize()
                    .unwrap()
                    .to_string_lossy()
                    .into_owned()
            }
        );
        assert_eq!(
            std::fs::read_to_string(&destination).unwrap(),
            "{\"evidence\":\"知識🦀\"}\n"
        );
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                std::fs::metadata(&destination)
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o600
            );
        }
    }
    assert_eq!(std::fs::read_dir(&fixture.output).unwrap().count(), 2);
}

#[test]
fn existing_work_and_unrelated_staging_are_preserved() {
    let fixture = Fixture::new();
    let target = fixture.output.join("review.json");
    let unrelated = fixture.output.join("review.json.part");
    std::fs::write(&target, "existing work").unwrap();
    std::fs::write(&unrelated, "unrelated staging").unwrap();
    assert_eq!(
        fixture.publish(&target).unwrap_err().code,
        "destinationExists"
    );
    assert_eq!(std::fs::read_to_string(target).unwrap(), "existing work");
    assert_eq!(
        std::fs::read_to_string(unrelated).unwrap(),
        "unrelated staging"
    );
    assert_eq!(std::fs::read_dir(&fixture.output).unwrap().count(), 2);
}

#[test]
fn evidence_change_or_invalid_destination_cannot_publish() {
    let fixture = Fixture::new();
    let target = fixture.output.join("review.json");
    assert_eq!(
        publish_package("old evidence", "new evidence", &target, &fixture.data)
            .unwrap_err()
            .code,
        "knowledgeChanged"
    );
    for selected in [
        fixture.data.join("review.json"),
        fixture.output.join("review.txt"),
        fixture.root.join("missing/review.json"),
        PathBuf::from("relative.json"),
    ] {
        assert_eq!(fixture.publish(&selected).unwrap_err().code, "destination");
    }
    assert_eq!(std::fs::read_dir(&fixture.output).unwrap().count(), 0);
    assert_eq!(std::fs::read_dir(&fixture.data).unwrap().count(), 0);
}

#[cfg(unix)]
#[test]
fn linked_destination_and_internal_directory_alias_cannot_replace_data() {
    let fixture = Fixture::new();
    let source = fixture.data.join("source.json");
    std::fs::write(&source, "retained original").unwrap();
    let target = fixture.output.join("linked.json");
    std::os::unix::fs::symlink(&source, &target).unwrap();
    assert_eq!(
        fixture.publish(&target).unwrap_err().code,
        "destinationExists"
    );
    let alias = fixture.output.join("alias");
    std::os::unix::fs::symlink(&fixture.data, &alias).unwrap();
    assert_eq!(
        fixture
            .publish(&alias.join("review.json"))
            .unwrap_err()
            .code,
        "destination"
    );
    assert_eq!(
        std::fs::read_to_string(source).unwrap(),
        "retained original"
    );
    assert_eq!(std::fs::read_dir(&fixture.output).unwrap().count(), 2);
}

fn wire() -> serde_json::Value {
    let sources: Vec<_> = ["projects/yap", "decisions/interface"].into_iter().map(|id| serde_json::json!({
        "node":{"conceptId":id,"type":"project","title":id,"sourcePath":format!("{id}.md"),"sourceRevision":"reviewed-1","contentSha256":"b".repeat(64)},
        "citation":{"conceptId":id,"sourceRevision":"reviewed-1","contentSha256":"b".repeat(64),"charStart":12,"charEnd":18},"text":"Source"
    })).collect();
    serde_json::json!({"schemaVersion":1,"proposalId":"f".repeat(64),"generationSha256":"a".repeat(64),
        "permissionHash":"c".repeat(64),"authorizationHash":"d".repeat(64),"status":"proposed",
        "candidate":{"schemaVersion":1,"sourceConceptId":"projects/yap","targetConceptId":"decisions/interface","relationshipType":"supports","rationale":"The cited decision supports this project."},"sources":sources})
}

#[test]
fn authenticated_reinspection_refuses_revoked_discarded_stale_or_changed_evidence_before_publication(
) {
    for scenario in [
        "success",
        "denied",
        "discarded",
        "identity",
        "generation",
        "evidence",
    ] {
        let fixture = Fixture::new();
        let target = fixture.output.join("review.json");
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let address = listener.local_addr().unwrap();
        let initial = wire();
        let mut changed = initial.clone();
        if scenario == "generation" {
            changed["generationSha256"] = serde_json::json!("e".repeat(64));
        }
        if scenario == "evidence" {
            changed["candidate"]["rationale"] = serde_json::json!("Changed rationale.");
        }
        let status = match scenario {
            "denied" => "403 Forbidden",
            "discarded" => "404 Not Found",
            "identity" => "401 Unauthorized",
            _ => "200 OK",
        };
        let server = thread::spawn(move || {
            let mut requests = Vec::new();
            for (status, body) in [
                ("200 OK", initial.to_string()),
                (status, changed.to_string()),
            ] {
                let (mut stream, _) = listener.accept().unwrap();
                let mut incoming = Vec::new();
                let mut chunk = [0u8; 4096];
                loop {
                    let count = stream.read(&mut chunk).unwrap();
                    if count == 0 {
                        break;
                    }
                    incoming.extend_from_slice(&chunk[..count]);
                    if incoming.windows(4).any(|part| part == b"\r\n\r\n") {
                        break;
                    }
                }
                requests.push(String::from_utf8(incoming).unwrap());
                write!(stream, "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).unwrap();
            }
            requests
        });
        let client = ConnectionsClient::new(
            AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "private-token"),
            &format!("http://{address}"),
        )
        .unwrap();
        let request = ConnectionsRequest::Proposal {
            proposal_id: "f".repeat(64),
        };
        let admitted =
            tauri::async_runtime::block_on(current_package(&client, &request, &"a".repeat(64)))
                .unwrap();
        // Exercise the picker interval through authenticated reinspection and actual
        // publication. Native lease invalidation has a separate connector test.
        let result =
            tauri::async_runtime::block_on(current_package(&client, &request, &"a".repeat(64)))
                .and_then(|current| publish_package(&admitted, &current, &target, &fixture.data));
        if scenario == "success" {
            assert!(result.is_ok());
            assert_eq!(std::fs::read_to_string(&target).unwrap(), admitted);
        } else {
            assert_eq!(
                result.unwrap_err().code,
                match scenario {
                    "denied" => "denied",
                    "discarded" => "notFound",
                    "identity" => "identityChanged",
                    _ => "knowledgeChanged",
                }
            );
            assert!(!target.exists());
            assert_eq!(std::fs::read_dir(&fixture.output).unwrap().count(), 0);
        }
        for incoming in server.join().unwrap() {
            assert!(incoming.starts_with(&format!(
                "GET /v1/knowledge/connection-proposal?proposalId={} HTTP/1.1",
                "f".repeat(64)
            )));
            assert!(incoming
                .to_lowercase()
                .contains("authorization: bearer private-token\r\n"));
            assert!(!incoming.contains("rationale") && !incoming.contains("subjectId"));
        }
    }
}
