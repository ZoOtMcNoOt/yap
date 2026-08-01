use std::time::Duration;

use reqwest::{Client, StatusCode};

use super::authorization::{AuthenticatedDispatchError, RequestAuthorizationError};
use super::config;
use super::state::ServerCapabilities;
use super::AuthenticatedRequestDispatcher;

const MAX_HEALTH_BYTES: usize = 64 * 1024;
const SUPPORTED_API_VERSION: &str = "1";

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum HealthCheckResult {
    Ready {
        api_version: String,
        capabilities: ServerCapabilities,
    },
    SignInRequired {
        api_version: Option<String>,
        capabilities: ServerCapabilities,
    },
    AccessDenied {
        api_version: Option<String>,
        capabilities: ServerCapabilities,
    },
    Offline {
        api_version: Option<String>,
        error_code: &'static str,
        retryable: bool,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum ProtectedAccessResult {
    Accepted,
    SignInRequired,
    AccessDenied,
    Unavailable {
        error_code: &'static str,
        retryable: bool,
    },
}

pub(crate) fn bounded_client() -> Result<Client, reqwest::Error> {
    Client::builder()
        .connect_timeout(Duration::from_secs(2))
        .timeout(Duration::from_secs(3))
        .redirect(reqwest::redirect::Policy::none())
        .no_proxy()
        // reqwest has no cookie store unless its optional cookies feature is enabled.
        .build()
}

pub(crate) async fn check_health(
    client: &Client,
    base_url: &str,
    allow_insecure_private: bool,
) -> HealthCheckResult {
    let normalized = match config::validate_base_url(base_url, allow_insecure_private) {
        Ok(normalized) => normalized,
        Err(_) => return offline(None, "INVALID_SERVER_URL", false),
    };
    let mut health_url = match reqwest::Url::parse(&normalized) {
        Ok(url) => url,
        Err(_) => return offline(None, "INVALID_SERVER_URL", false),
    };
    health_url.set_path("/v1/health");

    let response = match client
        .get(health_url)
        .header(reqwest::header::ACCEPT, "application/json")
        .send()
        .await
    {
        Ok(response) => response,
        Err(error) if error.is_connect() => return offline(None, "CONNECTION_FAILED", true),
        Err(error) if error.is_timeout() => return offline(None, "REQUEST_TIMEOUT", true),
        Err(_) => return offline(None, "CONNECTION_FAILED", true),
    };

    match response.status() {
        StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
            return HealthCheckResult::SignInRequired {
                api_version: None,
                capabilities: ServerCapabilities::default(),
            };
        }
        status if status.is_server_error() => return offline(None, "SERVER_ERROR", true),
        StatusCode::OK => {}
        _ => return offline(None, "UNEXPECTED_HTTP_STATUS", true),
    }

    let body = match read_bounded(response).await {
        Ok(body) => body,
        Err(ReadHealthBodyError::TooLarge) => {
            return offline(None, "HEALTH_RESPONSE_TOO_LARGE", true);
        }
        Err(ReadHealthBodyError::Transport(error)) if error.is_timeout() => {
            return offline(None, "REQUEST_TIMEOUT", true);
        }
        Err(ReadHealthBodyError::Transport(_)) => {
            return offline(None, "CONNECTION_FAILED", true);
        }
    };

    project_health(&body)
}

pub(super) async fn verify_protected_access(
    authenticated: &AuthenticatedRequestDispatcher,
    base_url: &str,
    allow_insecure_private: bool,
) -> ProtectedAccessResult {
    let normalized = match config::validate_base_url(base_url, allow_insecure_private) {
        Ok(normalized) => normalized,
        Err(_) => {
            return ProtectedAccessResult::Unavailable {
                error_code: "INVALID_SERVER_URL",
                retryable: false,
            };
        }
    };
    let mut url = match reqwest::Url::parse(&normalized) {
        Ok(url) => url,
        Err(_) => {
            return ProtectedAccessResult::Unavailable {
                error_code: "INVALID_SERVER_URL",
                retryable: false,
            };
        }
    };
    url.set_path("/v1/asr/capabilities");
    let response = match authenticated
        .send(
            authenticated
                .get(url)
                .header(reqwest::header::ACCEPT, "application/json"),
        )
        .await
    {
        Ok(response) => response,
        Err(AuthenticatedDispatchError::Authorization(
            RequestAuthorizationError::AccountChanged,
        )) => {
            return ProtectedAccessResult::AccessDenied;
        }
        Err(AuthenticatedDispatchError::Authorization(
            RequestAuthorizationError::Unavailable | RequestAuthorizationError::InvalidToken,
        )) => return ProtectedAccessResult::SignInRequired,
        Err(AuthenticatedDispatchError::Transport(error)) if error.is_timeout() => {
            return ProtectedAccessResult::Unavailable {
                error_code: "REQUEST_TIMEOUT",
                retryable: true,
            };
        }
        Err(AuthenticatedDispatchError::Transport(_)) => {
            return ProtectedAccessResult::Unavailable {
                error_code: "CONNECTION_FAILED",
                retryable: true,
            };
        }
    };
    let status = match response.status() {
        Ok(status) => status,
        Err(RequestAuthorizationError::AccountChanged) => {
            return ProtectedAccessResult::AccessDenied
        }
        Err(RequestAuthorizationError::Unavailable | RequestAuthorizationError::InvalidToken) => {
            return ProtectedAccessResult::SignInRequired
        }
    };
    match status {
        StatusCode::OK | StatusCode::NOT_IMPLEMENTED => ProtectedAccessResult::Accepted,
        StatusCode::UNAUTHORIZED => ProtectedAccessResult::SignInRequired,
        StatusCode::FORBIDDEN => ProtectedAccessResult::AccessDenied,
        StatusCode::SERVICE_UNAVAILABLE => ProtectedAccessResult::Unavailable {
            error_code: "AUTHENTICATION_UNAVAILABLE",
            retryable: true,
        },
        status if status.is_server_error() => ProtectedAccessResult::Unavailable {
            error_code: "SERVER_ERROR",
            retryable: true,
        },
        _ => ProtectedAccessResult::Unavailable {
            error_code: "UNEXPECTED_HTTP_STATUS",
            retryable: true,
        },
    }
}

#[derive(Debug, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct HealthEnvelope {
    service: String,
    status: String,
    api_version: String,
    auth: String,
    capabilities: Option<serde_json::Value>,
}

fn project_health(body: &[u8]) -> HealthCheckResult {
    let envelope: HealthEnvelope = match serde_json::from_slice(body) {
        Ok(envelope) => envelope,
        Err(_) => return offline(None, "MALFORMED_HEALTH_RESPONSE", true),
    };
    let api_version = Some(envelope.api_version.clone());
    if envelope.api_version != SUPPORTED_API_VERSION {
        return offline(api_version, "INCOMPATIBLE_API_VERSION", false);
    }
    let Some(capability_value) = envelope.capabilities else {
        return offline(api_version, "INCOMPATIBLE_CAPABILITIES", false);
    };
    let capabilities: ServerCapabilities = match serde_json::from_value(capability_value) {
        Ok(capabilities) => capabilities,
        Err(_) => return offline(api_version, "INCOMPATIBLE_CAPABILITIES", false),
    };
    if envelope.service != "yap-server" || envelope.status != "ok" {
        return offline(api_version, "MALFORMED_HEALTH_RESPONSE", true);
    }
    match envelope.auth.as_str() {
        "not_configured" => HealthCheckResult::Ready {
            api_version: envelope.api_version,
            capabilities,
        },
        "required" => HealthCheckResult::SignInRequired {
            api_version,
            capabilities,
        },
        _ => offline(api_version, "MALFORMED_HEALTH_RESPONSE", true),
    }
}

fn offline(
    api_version: Option<String>,
    error_code: &'static str,
    retryable: bool,
) -> HealthCheckResult {
    HealthCheckResult::Offline {
        api_version,
        error_code,
        retryable,
    }
}

#[derive(Debug)]
enum ReadHealthBodyError {
    TooLarge,
    Transport(reqwest::Error),
}

async fn read_bounded(mut response: reqwest::Response) -> Result<Vec<u8>, ReadHealthBodyError> {
    if response
        .content_length()
        .is_some_and(|length| length > MAX_HEALTH_BYTES as u64)
    {
        return Err(ReadHealthBodyError::TooLarge);
    }
    let mut body = Vec::with_capacity(
        response
            .content_length()
            .unwrap_or_default()
            .min(MAX_HEALTH_BYTES as u64) as usize,
    );
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(ReadHealthBodyError::Transport)?
    {
        if body.len().saturating_add(chunk.len()) > MAX_HEALTH_BYTES {
            return Err(ReadHealthBodyError::TooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

#[cfg(test)]
mod tests;
