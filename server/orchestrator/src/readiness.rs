use std::time::Duration;

use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::time::timeout;

use crate::config::SupervisedServiceConfig;
use crate::endpoint::NumericLoopbackEndpoint;

const HTTP_TIMEOUT: Duration = Duration::from_millis(500);
const MAXIMUM_HTTP_RESPONSE_BYTES: usize = 64 * 1024;

pub(crate) async fn probe_exact_service(config: &SupervisedServiceConfig) -> bool {
    let Some(health_response) = request_loopback(config.endpoint(), "/health").await else {
        return false;
    };
    if parse_success_body(&health_response).is_none() {
        return false;
    }
    let Some(model_response) = request_loopback(config.endpoint(), "/v1/models").await else {
        return false;
    };
    let Some(body) = parse_success_body(&model_response) else {
        return false;
    };
    let Ok(value) = serde_json::from_slice::<serde_json::Value>(body) else {
        return false;
    };
    let Some(models) = value
        .as_object()
        .and_then(|object| object.get("data"))
        .and_then(serde_json::Value::as_array)
    else {
        return false;
    };
    models.len() == 1
        && models[0]
            .as_object()
            .and_then(|model| model.get("id"))
            .and_then(serde_json::Value::as_str)
            == Some(config.expected_model())
}

async fn request_loopback(endpoint: NumericLoopbackEndpoint, target: &str) -> Option<Vec<u8>> {
    timeout(HTTP_TIMEOUT, async move {
        let mut stream = TcpStream::connect(endpoint.socket_addr()).await.ok()?;
        let request = format!(
            "GET {target} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n\r\n",
            endpoint.authority()
        );
        stream.write_all(request.as_bytes()).await.ok()?;
        let mut response = Vec::new();
        let mut buffer = [0_u8; 4096];
        loop {
            let count = stream.read(&mut buffer).await.ok()?;
            if count == 0 {
                break;
            }
            if response.len().saturating_add(count) > MAXIMUM_HTTP_RESPONSE_BYTES {
                return None;
            }
            response.extend_from_slice(&buffer[..count]);
        }
        Some(response)
    })
    .await
    .ok()
    .flatten()
}

fn parse_success_body(response: &[u8]) -> Option<&[u8]> {
    let separator = response.windows(4).position(|value| value == b"\r\n\r\n")?;
    let headers = std::str::from_utf8(&response[..separator]).ok()?;
    let status = headers.lines().next()?;
    if status != "HTTP/1.1 200 OK" && status != "HTTP/1.0 200 OK" {
        return None;
    }
    Some(&response[separator + 4..])
}
