use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

use super::{
    bounded_client, check_health, verify_protected_access, HealthCheckResult, ProtectedAccessResult,
};
use crate::server_connector::state::ServerCapabilities;
use crate::server_connector::AuthenticatedRequestDispatcher;

struct Fixture {
    address: SocketAddr,
    request: Arc<Mutex<Vec<u8>>>,
    worker: Option<JoinHandle<()>>,
}

impl Fixture {
    fn response(status: &str, body: impl Into<Vec<u8>>, delay: Duration) -> Self {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let address = listener.local_addr().unwrap();
        let status = status.to_owned();
        let body = body.into();
        let request = Arc::new(Mutex::new(Vec::new()));
        let captured_request = Arc::clone(&request);
        let worker = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0_u8; 1024];
            let read = stream.read(&mut request).unwrap_or(0);
            captured_request
                .lock()
                .unwrap()
                .extend_from_slice(&request[..read]);
            if !delay.is_zero() {
                std::thread::sleep(delay);
            }
            let response = format!(
                "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            );
            let _ = stream.write_all(response.as_bytes());
            let _ = stream.write_all(&body);
        });
        Self {
            address,
            request,
            worker: Some(worker),
        }
    }

    fn base_url(&self) -> String {
        format!("http://{}", self.address)
    }

    fn request_text(&self) -> String {
        String::from_utf8(self.request.lock().unwrap().clone()).unwrap()
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        if let Some(worker) = self.worker.take() {
            worker.join().unwrap();
        }
    }
}

fn check(base_url: &str) -> HealthCheckResult {
    let client = bounded_client().unwrap();
    tauri::async_runtime::block_on(check_health(&client, base_url, false))
}

fn check_protected(base_url: &str) -> ProtectedAccessResult {
    let authenticated =
        AuthenticatedRequestDispatcher::fixed(bounded_client().unwrap(), "protected-probe-token");
    tauri::async_runtime::block_on(verify_protected_access(&authenticated, base_url, false))
}

fn healthy_body(api_version: &str, auth: &str, capabilities: &str) -> String {
    format!(
        r#"{{"service":"yap-server","status":"ok","apiVersion":"{api_version}","auth":"{auth}","capabilities":{capabilities}}}"#
    )
}

#[test]
fn healthy_v1_response_advertises_only_server_capabilities() {
    let fixture = Fixture::response(
        "200 OK",
        healthy_body(
            "1",
            "not_configured",
            r#"{"batchJobs":true,"liveStreaming":false,"jobStatus":true}"#,
        ),
        Duration::ZERO,
    );

    assert_eq!(
        check(&fixture.base_url()),
        HealthCheckResult::Ready {
            api_version: "1".to_owned(),
            capabilities: ServerCapabilities {
                batch_jobs: true,
                live_streaming: false,
                job_status: true,
            },
        }
    );
}

#[test]
fn unsupported_version_fails_closed_without_retry() {
    let fixture = Fixture::response(
        "200 OK",
        healthy_body(
            "2",
            "not_configured",
            r#"{"batchJobs":true,"liveStreaming":true,"jobStatus":true}"#,
        ),
        Duration::ZERO,
    );

    assert_eq!(
        check(&fixture.base_url()),
        HealthCheckResult::Offline {
            api_version: Some("2".to_owned()),
            error_code: "INCOMPATIBLE_API_VERSION",
            retryable: false,
        }
    );
}

#[test]
fn malformed_capabilities_fail_closed_as_incompatible() {
    let fixture = Fixture::response(
        "200 OK",
        healthy_body(
            "1",
            "not_configured",
            r#"{"batchJobs":"yes","liveStreaming":true,"jobStatus":true}"#,
        ),
        Duration::ZERO,
    );

    assert_eq!(
        check(&fixture.base_url()),
        HealthCheckResult::Offline {
            api_version: Some("1".to_owned()),
            error_code: "INCOMPATIBLE_CAPABILITIES",
            retryable: false,
        }
    );
}

#[test]
fn absent_capability_object_fails_closed_without_retry() {
    let fixture = Fixture::response(
        "200 OK",
        br#"{"service":"yap-server","status":"ok","apiVersion":"1","auth":"not_configured"}"#
            .to_vec(),
        Duration::ZERO,
    );

    assert_eq!(
        check(&fixture.base_url()),
        HealthCheckResult::Offline {
            api_version: Some("1".to_owned()),
            error_code: "INCOMPATIBLE_CAPABILITIES",
            retryable: false,
        }
    );
}

#[test]
fn missing_capability_field_fails_closed_without_retry() {
    let fixture = Fixture::response(
        "200 OK",
        healthy_body(
            "1",
            "not_configured",
            r#"{"batchJobs":true,"liveStreaming":true}"#,
        ),
        Duration::ZERO,
    );

    assert_eq!(
        check(&fixture.base_url()),
        HealthCheckResult::Offline {
            api_version: Some("1".to_owned()),
            error_code: "INCOMPATIBLE_CAPABILITIES",
            retryable: false,
        }
    );
}

#[test]
fn malformed_json_is_retryable_and_fail_closed() {
    let fixture = Fixture::response("200 OK", b"{not-json".to_vec(), Duration::ZERO);

    assert_eq!(
        check(&fixture.base_url()),
        HealthCheckResult::Offline {
            api_version: None,
            error_code: "MALFORMED_HEALTH_RESPONSE",
            retryable: true,
        }
    );
}

#[test]
fn authentication_status_and_health_auth_require_sign_in() {
    for status in ["401 Unauthorized", "403 Forbidden"] {
        let fixture = Fixture::response(status, Vec::new(), Duration::ZERO);
        assert_eq!(
            check(&fixture.base_url()),
            HealthCheckResult::SignInRequired {
                api_version: None,
                capabilities: ServerCapabilities::default(),
            }
        );
    }

    let fixture = Fixture::response(
        "200 OK",
        healthy_body(
            "1",
            "required",
            r#"{"batchJobs":true,"liveStreaming":true,"jobStatus":true}"#,
        ),
        Duration::ZERO,
    );
    assert_eq!(
        check(&fixture.base_url()),
        HealthCheckResult::SignInRequired {
            api_version: Some("1".to_owned()),
            capabilities: ServerCapabilities {
                batch_jobs: true,
                live_streaming: true,
                job_status: true,
            },
        }
    );
}

#[test]
fn protected_probe_requires_actual_principal_admission_and_sends_the_bearer() {
    for (status, expected) in [
        ("200 OK", ProtectedAccessResult::Accepted),
        ("401 Unauthorized", ProtectedAccessResult::SignInRequired),
        ("403 Forbidden", ProtectedAccessResult::AccessDenied),
        (
            "503 Service Unavailable",
            ProtectedAccessResult::Unavailable {
                error_code: "AUTHENTICATION_UNAVAILABLE",
                retryable: true,
            },
        ),
    ] {
        let fixture = Fixture::response(status, Vec::new(), Duration::ZERO);

        assert_eq!(check_protected(&fixture.base_url()), expected);
        let request = fixture.request_text().to_ascii_lowercase();
        assert!(request.starts_with("get /v1/asr/capabilities http/1.1\r\n"));
        assert!(request.contains("authorization: bearer protected-probe-token\r\n"));
    }
}

#[test]
fn python_authenticated_server_accepts_signed_bearer_when_provided() {
    let (Ok(base_url), Ok(token)) = (
        std::env::var("YAP_TEST_AUTH_SERVER_URL"),
        std::env::var("YAP_TEST_AUTH_SERVER_TOKEN"),
    ) else {
        return;
    };
    let authenticated = AuthenticatedRequestDispatcher::fixed(bounded_client().unwrap(), &token);
    let result =
        tauri::async_runtime::block_on(verify_protected_access(&authenticated, &base_url, false));

    assert_eq!(result, ProtectedAccessResult::Accepted);
}

#[test]
fn server_errors_and_connection_refusal_are_retryable() {
    let fixture = Fixture::response("500 Internal Server Error", Vec::new(), Duration::ZERO);
    assert_eq!(
        check(&fixture.base_url()),
        HealthCheckResult::Offline {
            api_version: None,
            error_code: "SERVER_ERROR",
            retryable: true,
        }
    );

    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let refused = format!("http://{}", listener.local_addr().unwrap());
    drop(listener);
    assert_eq!(
        check(&refused),
        HealthCheckResult::Offline {
            api_version: None,
            error_code: "CONNECTION_FAILED",
            retryable: true,
        }
    );
}

#[test]
fn delayed_response_hits_the_three_second_total_timeout() {
    let fixture = Fixture::response(
        "200 OK",
        healthy_body(
            "1",
            "not_configured",
            r#"{"batchJobs":false,"liveStreaming":false,"jobStatus":false}"#,
        ),
        Duration::from_millis(3_100),
    );

    assert_eq!(
        check(&fixture.base_url()),
        HealthCheckResult::Offline {
            api_version: None,
            error_code: "REQUEST_TIMEOUT",
            retryable: true,
        }
    );
}

#[test]
fn response_body_is_bounded_to_sixty_four_kibibytes() {
    let fixture = Fixture::response("200 OK", vec![b'x'; 65_537], Duration::ZERO);

    assert_eq!(
        check(&fixture.base_url()),
        HealthCheckResult::Offline {
            api_version: None,
            error_code: "HEALTH_RESPONSE_TOO_LARGE",
            retryable: true,
        }
    );
}

#[test]
fn invalid_url_is_rejected_before_network_io() {
    assert_eq!(
        check("http://example.com"),
        HealthCheckResult::Offline {
            api_version: None,
            error_code: "INVALID_SERVER_URL",
            retryable: false,
        }
    );
}
