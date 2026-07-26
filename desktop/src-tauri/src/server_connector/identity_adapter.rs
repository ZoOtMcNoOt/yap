mod process;
mod protocol;

use std::{
    future::Future,
    pin::Pin,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
    time::{SystemTime, UNIX_EPOCH},
};

use sha2::{Digest, Sha256};
use tokio::sync::Mutex;
use zeroize::Zeroizing;

use super::{
    authorization::{
        AccessToken, AccessTokenFuture, AccountBinding, AuthorizedAccess,
        RequestAuthorizationError, ServerAccessTokenSource,
    },
    config::{MicrosoftEntraSettings, ServerSettings},
};
use process::ProcessIdentityAdapter;
use protocol::{
    IdentityAdapterProtocolError, IdentityAdapterRequest, IdentityAdapterResponse,
    IdentityOperation, IdentityOutcome,
};

const TOKEN_REFRESH_MARGIN_SECONDS: u64 = 120;

type IdentityAdapterFuture<'a> = Pin<
    Box<
        dyn Future<Output = Result<IdentityAdapterResponse, IdentityAdapterProtocolError>>
            + Send
            + 'a,
    >,
>;

trait IdentityAdapter: Send + Sync {
    fn execute(&self, request: IdentityAdapterRequest) -> IdentityAdapterFuture<'_>;
}

type SettingsLoader = dyn Fn() -> Result<ServerSettings, super::config::ConfigError> + Send + Sync;

struct CachedAccessToken {
    configuration: MicrosoftEntraSettings,
    value: Zeroizing<String>,
    account_binding: AccountBinding,
    expires_at_unix_seconds: u64,
}

#[derive(Default)]
struct IdentityState {
    cached_token: Option<CachedAccessToken>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct IdentitySessionStatus {
    pub(crate) configured: bool,
    pub(crate) signed_in: bool,
}

pub(super) struct NativeIdentityManager {
    adapter: Option<Arc<dyn IdentityAdapter>>,
    settings_loader: Arc<SettingsLoader>,
    state: Mutex<IdentityState>,
    request_sequence: AtomicU64,
}

impl NativeIdentityManager {
    pub(super) fn discover() -> Arc<Self> {
        Arc::new(Self {
            adapter: ProcessIdentityAdapter::discover()
                .ok()
                .map(|adapter| Arc::new(adapter) as Arc<dyn IdentityAdapter>),
            settings_loader: Arc::new(super::config::load),
            state: Mutex::new(IdentityState::default()),
            request_sequence: AtomicU64::new(0),
        })
    }

    async fn access_token(&self) -> Result<Option<AuthorizedAccess>, RequestAuthorizationError> {
        let Some(configuration) = self.load_configuration()? else {
            self.state.lock().await.cached_token = None;
            return Ok(None);
        };
        let mut state = self.state.lock().await;
        let now = now_unix_seconds();
        if let Some(cached) = state.cached_token.as_ref() {
            if cached.configuration == configuration
                && cached.expires_at_unix_seconds > now.saturating_add(TOKEN_REFRESH_MARGIN_SECONDS)
            {
                return Ok(Some(AuthorizedAccess::new(
                    AccessToken::new(cached.value.to_string())?,
                    cached.account_binding.clone(),
                )));
            }
        }
        state.cached_token = None;
        let response = self
            .execute(IdentityOperation::AcquireTokenSilent, &configuration, None)
            .await
            .map_err(|error| match error {
                IdentityAdapterProtocolError::InvalidResponse => {
                    RequestAuthorizationError::InvalidToken
                }
                IdentityAdapterProtocolError::Unavailable
                | IdentityAdapterProtocolError::TimedOut => RequestAuthorizationError::Unavailable,
            })?;
        match response.outcome {
            IdentityOutcome::Token => {
                let token = response
                    .access_token
                    .ok_or(RequestAuthorizationError::InvalidToken)?;
                let expires_at = response
                    .expires_at_unix_seconds
                    .ok_or(RequestAuthorizationError::InvalidToken)?;
                if expires_at <= now {
                    return Err(RequestAuthorizationError::InvalidToken);
                }
                let account_binding = account_binding(
                    response
                        .account_id
                        .as_deref()
                        .ok_or(RequestAuthorizationError::InvalidToken)?,
                )?;
                let outbound = AccessToken::new(token.to_string())?;
                state.cached_token = Some(CachedAccessToken {
                    configuration,
                    value: token,
                    account_binding: account_binding.clone(),
                    expires_at_unix_seconds: expires_at,
                });
                Ok(Some(AuthorizedAccess::new(outbound, account_binding)))
            }
            IdentityOutcome::InteractionRequired | IdentityOutcome::Unavailable => {
                Err(RequestAuthorizationError::Unavailable)
            }
            _ => Err(RequestAuthorizationError::InvalidToken),
        }
    }

    pub(super) async fn status(&self) -> Result<IdentitySessionStatus, String> {
        let Some(configuration) = self
            .load_configuration()
            .map_err(|_| "Server identity configuration is unavailable.")?
        else {
            self.state.lock().await.cached_token = None;
            return Ok(IdentitySessionStatus {
                configured: false,
                signed_in: false,
            });
        };
        let mut state = self.state.lock().await;
        let response = self
            .execute(IdentityOperation::GetStatus, &configuration, None)
            .await
            .map_err(project_identity_error)?;
        let signed_in = if response.outcome == IdentityOutcome::SignedInStatus {
            let current_binding = account_binding(
                response
                    .account_id
                    .as_deref()
                    .ok_or("Microsoft Entra returned an invalid account identity.")?,
            )
            .map_err(|_| "Microsoft Entra returned an invalid account identity.")?;
            if state
                .cached_token
                .as_ref()
                .is_some_and(|cached| cached.account_binding != current_binding)
            {
                state.cached_token = None;
            }
            true
        } else {
            state.cached_token = None;
            false
        };
        Ok(IdentitySessionStatus {
            configured: true,
            signed_in,
        })
    }

    pub(super) async fn sign_in(&self, parent_window_handle: Option<u64>) -> Result<(), String> {
        let configuration = self
            .load_configuration()
            .map_err(|_| "Server identity configuration is unavailable.")?
            .ok_or("Configure Microsoft Entra before signing in.")?;
        let mut state = self.state.lock().await;
        state.cached_token = None;
        let response = self
            .execute(
                IdentityOperation::SignInInteractively,
                &configuration,
                parent_window_handle,
            )
            .await
            .map_err(project_identity_error)?;
        if response.outcome != IdentityOutcome::SignedIn {
            return Err("Microsoft Entra sign-in did not complete.".into());
        }
        let token = response
            .access_token
            .ok_or("Microsoft Entra returned an invalid sign-in response.")?;
        let expires_at = response
            .expires_at_unix_seconds
            .ok_or("Microsoft Entra returned an invalid sign-in response.")?;
        if expires_at <= now_unix_seconds() {
            return Err("Microsoft Entra returned an expired access token.".into());
        }
        let account_binding = account_binding(
            response
                .account_id
                .as_deref()
                .ok_or("Microsoft Entra returned an invalid sign-in response.")?,
        )
        .map_err(|_| "Microsoft Entra returned an invalid account identity.")?;
        AccessToken::new(token.to_string())
            .map_err(|_| "Microsoft Entra returned an invalid access token.")?;
        state.cached_token = Some(CachedAccessToken {
            configuration,
            value: token,
            account_binding,
            expires_at_unix_seconds: expires_at,
        });
        Ok(())
    }

    pub(super) async fn sign_out(&self) -> Result<(), String> {
        let Some(configuration) = self
            .load_configuration()
            .map_err(|_| "Server identity configuration is unavailable.")?
        else {
            self.state.lock().await.cached_token = None;
            return Ok(());
        };
        let mut state = self.state.lock().await;
        state.cached_token = None;
        let response = self
            .execute(IdentityOperation::SignOut, &configuration, None)
            .await
            .map_err(project_identity_error)?;
        if response.outcome != IdentityOutcome::SignedOut {
            return Err("Microsoft Entra sign-out did not complete.".into());
        }
        Ok(())
    }

    pub(super) async fn configuration_changed(&self, previous: Option<&MicrosoftEntraSettings>) {
        let mut state = self.state.lock().await;
        state.cached_token = None;
        let Some(previous) = previous else {
            return;
        };
        match self.execute(IdentityOperation::SignOut, previous, None).await {
            Ok(response) if response.outcome == IdentityOutcome::SignedOut => {}
            Ok(_) => crate::diagnostics::log(
                "previous Microsoft Entra session cleanup did not complete after configuration change",
            ),
            Err(_) => crate::diagnostics::log(
                "previous Microsoft Entra session cleanup is unavailable after configuration change",
            ),
        }
    }

    fn load_configuration(
        &self,
    ) -> Result<Option<MicrosoftEntraSettings>, RequestAuthorizationError> {
        (self.settings_loader)()
            .map(|settings| settings.authentication)
            .map_err(|_| RequestAuthorizationError::Unavailable)
    }

    async fn execute(
        &self,
        operation: IdentityOperation,
        settings: &MicrosoftEntraSettings,
        parent_window_handle: Option<u64>,
    ) -> Result<IdentityAdapterResponse, IdentityAdapterProtocolError> {
        let adapter = self
            .adapter
            .as_ref()
            .ok_or(IdentityAdapterProtocolError::Unavailable)?;
        let request_id = format!(
            "identity-{}-{}",
            std::process::id(),
            self.request_sequence.fetch_add(1, Ordering::Relaxed)
        );
        adapter
            .execute(IdentityAdapterRequest::new(
                request_id,
                operation,
                settings,
                parent_window_handle,
            ))
            .await
    }
}

impl ServerAccessTokenSource for NativeIdentityManager {
    fn access(&self) -> AccessTokenFuture<'_> {
        Box::pin(self.access_token())
    }
}

fn account_binding(account_id: &str) -> Result<AccountBinding, RequestAuthorizationError> {
    let mut digest = Sha256::new();
    digest.update(b"yap-account-binding-v1\0");
    digest.update(account_id.as_bytes());
    let value = digest
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    AccountBinding::new(value)
}

fn now_unix_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn project_identity_error(error: IdentityAdapterProtocolError) -> String {
    match error {
        IdentityAdapterProtocolError::TimedOut => "Microsoft Entra did not respond in time.".into(),
        IdentityAdapterProtocolError::Unavailable => {
            "Microsoft Entra sign-in is unavailable on this installation.".into()
        }
        IdentityAdapterProtocolError::InvalidResponse => {
            "Microsoft Entra returned an incompatible response.".into()
        }
    }
}

#[cfg(test)]
mod tests;
