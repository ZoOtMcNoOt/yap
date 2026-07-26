use std::time::Duration;

use tauri::{Emitter, Manager};

mod identity;
mod settings;

pub(super) use identity::{
    session_status as identity_session_status, sign_in as sign_in_to_server,
    sign_out as sign_out_of_server,
};
#[cfg(test)]
pub(super) use settings::{
    finish_save as finish_settings_save,
    requires_origin_confirmation as requires_server_origin_confirmation,
};
pub(super) use settings::{load as load_settings, save as save_settings};

use super::{
    allow_insecure_private_server, capabilities, client, config, AsrCapabilityCatalog,
    ServerConnectionSnapshot, ServerConnector,
};

struct FetchedAsrCapabilityCatalog {
    lease: super::core::AsrCapabilityLease,
    catalog: AsrCapabilityCatalog,
}

impl ServerConnector {
    fn synchronize_from_disk(
        &self,
        app: &tauri::AppHandle,
    ) -> Result<ServerConnectionSnapshot, config::ConfigError> {
        self.with_loaded_settings(config::load, |inner, settings| {
            self.synchronize_settings_locked(inner, &settings, |snapshot| {
                emit_transition(app, snapshot);
            })
        })
    }

    pub(crate) async fn refresh_for_job_drain(
        &self,
        app: &tauri::AppHandle,
    ) -> ServerConnectionSnapshot {
        if self.synchronize_from_disk(app).is_err() {
            return self.snapshot();
        }
        self.refresh(app).await
    }

    async fn refresh<R: tauri::Runtime>(
        &self,
        app: &tauri::AppHandle<R>,
    ) -> ServerConnectionSnapshot {
        let Some((generation, base_url)) = self.begin_health_request_with(|snapshot| {
            emit_transition(app, snapshot);
        }) else {
            return self.snapshot();
        };

        let result = check_health_for_approved_origin(
            &self.client,
            &base_url,
            allow_insecure_private_server(),
            config::origin_is_approved,
        )
        .await;
        let result = resolve_health_authentication(
            result,
            &self.authenticated,
            generation,
            &base_url,
            allow_insecure_private_server(),
        )
        .await;
        let retry_app = app.clone();
        self.accept_health_result_with(
            generation,
            result,
            |snapshot| emit_transition(app, snapshot),
            move |generation, retry_token, delay| {
                spawn_retry(retry_app, generation, retry_token, delay)
            },
        )
    }
}

fn emit_transition<R: tauri::Runtime>(
    app: &tauri::AppHandle<R>,
    snapshot: &ServerConnectionSnapshot,
) {
    if let Err(error) = app.emit_to(
        crate::authorization::MAIN_WINDOW_LABEL,
        "server-connection",
        snapshot.clone(),
    ) {
        crate::diagnostics::log(&format!("server connection event failed: {error}"));
    }
}

pub(super) async fn check_health_for_approved_origin<Authorize>(
    client: &reqwest::Client,
    base_url: &str,
    allow_insecure_private: bool,
    authorize: Authorize,
) -> client::HealthCheckResult
where
    Authorize: FnOnce(&str) -> Result<bool, config::ConfigError>,
{
    if !authorize(base_url).unwrap_or(false) {
        return client::HealthCheckResult::Offline {
            api_version: None,
            error_code: "UNAPPROVED_SERVER_ORIGIN",
            retryable: false,
        };
    }
    client::check_health(client, base_url, allow_insecure_private).await
}

async fn resolve_health_authentication(
    result: client::HealthCheckResult,
    authenticated: &super::AuthenticatedRequestDispatcher,
    generation: u64,
    base_url: &str,
    allow_insecure_private: bool,
) -> client::HealthCheckResult {
    if !matches!(
        result,
        client::HealthCheckResult::SignInRequired {
            api_version: Some(_),
            ..
        }
    ) {
        return result;
    }
    let authenticated = match authenticated.bind_current_transport(generation, base_url) {
        Ok(authenticated) => authenticated,
        Err(_) => {
            return client::HealthCheckResult::Offline {
                api_version: None,
                error_code: "SERVER_CONFIGURATION_CHANGED",
                retryable: false,
            };
        }
    };
    let access =
        client::verify_protected_access(&authenticated, base_url, allow_insecure_private).await;
    project_authenticated_health(result, access)
}

fn project_authenticated_health(
    result: client::HealthCheckResult,
    access: client::ProtectedAccessResult,
) -> client::HealthCheckResult {
    match result {
        client::HealthCheckResult::SignInRequired {
            api_version: Some(api_version),
            capabilities,
        } => match access {
            client::ProtectedAccessResult::Accepted => client::HealthCheckResult::Ready {
                api_version,
                capabilities,
            },
            client::ProtectedAccessResult::SignInRequired => {
                client::HealthCheckResult::SignInRequired {
                    api_version: Some(api_version),
                    capabilities,
                }
            }
            client::ProtectedAccessResult::AccessDenied => {
                client::HealthCheckResult::AccessDenied {
                    api_version: Some(api_version),
                    capabilities,
                }
            }
            client::ProtectedAccessResult::Unavailable {
                error_code,
                retryable,
            } => client::HealthCheckResult::Offline {
                api_version: Some(api_version),
                error_code,
                retryable,
            },
        },
        result => result,
    }
}

fn spawn_retry<R: tauri::Runtime>(
    app: tauri::AppHandle<R>,
    generation: u64,
    retry_token: u64,
    delay: Duration,
) -> tauri::async_runtime::JoinHandle<()> {
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(delay).await;
        Box::pin(run_scheduled_retry(app, generation, retry_token)).await;
    })
}

async fn run_scheduled_retry<R: tauri::Runtime>(
    app: tauri::AppHandle<R>,
    generation: u64,
    retry_token: u64,
) {
    let connector = app.state::<ServerConnector>();
    let Some(base_url) =
        connector.begin_scheduled_retry_with(generation, retry_token, |snapshot| {
            emit_transition(&app, snapshot);
        })
    else {
        return;
    };

    let result = check_health_for_approved_origin(
        &connector.client,
        &base_url,
        allow_insecure_private_server(),
        config::origin_is_approved,
    )
    .await;
    let result = resolve_health_authentication(
        result,
        &connector.authenticated,
        generation,
        &base_url,
        allow_insecure_private_server(),
    )
    .await;
    let retry_app = app.clone();
    connector.accept_health_result_with(
        generation,
        result,
        |snapshot| emit_transition(&app, snapshot),
        move |generation, retry_token, delay| {
            spawn_retry(retry_app, generation, retry_token, delay)
        },
    );
}

pub(super) fn connection_status(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<ServerConnectionSnapshot, String> {
    crate::authorization::ensure_main(&window)?;
    connector
        .synchronize_from_disk(&app)
        .map_err(|error| error.to_string())
}

pub(super) async fn refresh_connection(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<ServerConnectionSnapshot, String> {
    crate::authorization::ensure_main(&window)?;
    connector
        .synchronize_from_disk(&app)
        .map_err(|error| error.to_string())?;
    Ok(connector.refresh(&app).await)
}

pub(super) async fn asr_capabilities(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    connector: tauri::State<'_, ServerConnector>,
) -> Result<Option<AsrCapabilityCatalog>, String> {
    crate::authorization::ensure_main(&window)?;
    current_asr_capabilities(&app, connector.inner()).await
}

pub(crate) async fn current_asr_capabilities(
    app: &tauri::AppHandle,
    connector: &ServerConnector,
) -> Result<Option<AsrCapabilityCatalog>, String> {
    with_current_asr_capabilities(app, connector, |current| current.catalog().clone()).await
}

pub(crate) async fn with_current_asr_capabilities<T>(
    app: &tauri::AppHandle,
    connector: &ServerConnector,
    commit: impl FnOnce(super::CurrentAsrCatalog<'_>) -> T,
) -> Result<Option<T>, String> {
    let Some(fetched) = fetch_current_asr_capabilities(app, connector).await? else {
        return Ok(None);
    };
    // This synchronous closure runs while the connector generation is locked.
    // Callers use it for bounded durable commits; it must never await or acquire
    // the connector in the opposite order.
    connector
        .commit_current_asr_capability_catalog(&fetched.lease, fetched.catalog, commit)
        .map(Some)
}

async fn fetch_current_asr_capabilities(
    app: &tauri::AppHandle,
    connector: &ServerConnector,
) -> Result<Option<FetchedAsrCapabilityCatalog>, String> {
    connector
        .synchronize_from_disk(app)
        .map_err(|error| error.to_string())?;
    let Some(lease) = connector.asr_capability_lease() else {
        return Ok(None);
    };
    if !config::origin_is_approved(lease.base_url()).unwrap_or(false) {
        return Err("ASR capability origin is not approved.".into());
    }
    let catalog = match capabilities::fetch_asr_capabilities(
        lease.authenticated(),
        lease.base_url(),
        allow_insecure_private_server(),
    )
    .await
    {
        Ok(catalog) => catalog,
        Err(
            capabilities::AsrCatalogError::Transport | capabilities::AsrCatalogError::Unavailable,
        ) => return Ok(None),
        Err(capabilities::AsrCatalogError::InvalidOrigin) => {
            return Err("ASR capability origin is invalid.".into());
        }
        Err(
            capabilities::AsrCatalogError::ResponseTooLarge
            | capabilities::AsrCatalogError::Malformed
            | capabilities::AsrCatalogError::RevisionMismatch,
        ) => return Err("Server returned an incompatible ASR capability catalog.".into()),
    };
    Ok(Some(FetchedAsrCapabilityCatalog { lease, catalog }))
}

pub(crate) fn last_known_asr_capabilities(
) -> Result<Option<super::LastKnownAsrCapabilities>, String> {
    let settings = config::load().map_err(|error| error.to_string())?;
    if !settings.enabled {
        return Ok(None);
    }
    let Some(origin) = settings.base_url else {
        return Ok(None);
    };
    match super::capability_snapshot::load(&origin) {
        Ok(snapshot) => Ok(snapshot),
        Err(_) => {
            crate::diagnostics::log("last-known ASR capability snapshot is unavailable");
            Ok(None)
        }
    }
}

#[cfg(test)]
mod authentication_projection_tests {
    use super::project_authenticated_health;
    use crate::server_connector::{
        client::{HealthCheckResult, ProtectedAccessResult},
        state::ServerCapabilities,
    };

    fn protected_health() -> HealthCheckResult {
        HealthCheckResult::SignInRequired {
            api_version: Some("1".to_owned()),
            capabilities: ServerCapabilities {
                batch_jobs: true,
                live_streaming: false,
                job_status: true,
            },
        }
    }

    #[test]
    fn token_promotes_public_protected_health_to_ready() {
        assert!(matches!(
            project_authenticated_health(protected_health(), ProtectedAccessResult::Accepted),
            HealthCheckResult::Ready {
                api_version,
                capabilities,
            } if api_version == "1"
                && capabilities.batch_jobs
                && capabilities.job_status
                && !capabilities.live_streaming
        ));
    }

    #[test]
    fn missing_token_keeps_public_protected_health_signed_out() {
        assert!(matches!(
            project_authenticated_health(
                protected_health(),
                ProtectedAccessResult::SignInRequired,
            ),
            HealthCheckResult::SignInRequired {
                api_version: Some(api_version),
                ..
            } if api_version == "1"
        ));
    }

    #[test]
    fn token_does_not_promote_an_unauthorized_health_response() {
        assert!(matches!(
            project_authenticated_health(
                HealthCheckResult::SignInRequired {
                    api_version: None,
                    capabilities: ServerCapabilities::default(),
                },
                ProtectedAccessResult::Accepted,
            ),
            HealthCheckResult::SignInRequired {
                api_version: None,
                ..
            }
        ));
    }

    #[test]
    fn denied_access_is_distinct_from_missing_sign_in() {
        assert!(matches!(
            project_authenticated_health(
                protected_health(),
                ProtectedAccessResult::AccessDenied,
            ),
            HealthCheckResult::AccessDenied {
                api_version: Some(api_version),
                ..
            } if api_version == "1"
        ));
    }

    #[test]
    fn unavailable_admission_is_retryable_without_claiming_readiness() {
        assert!(matches!(
            project_authenticated_health(
                protected_health(),
                ProtectedAccessResult::Unavailable {
                    error_code: "AUTHENTICATION_UNAVAILABLE",
                    retryable: true,
                },
            ),
            HealthCheckResult::Offline {
                api_version: Some(api_version),
                error_code: "AUTHENTICATION_UNAVAILABLE",
                retryable: true,
            } if api_version == "1"
        ));
    }
}
