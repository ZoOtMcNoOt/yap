use std::{
    future::Future,
    pin::Pin,
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use sha2::{Digest, Sha256};
use tokio::sync::Mutex;
use zeroize::Zeroizing;

use super::{
    authorization::{
        AccessToken, AccessTokenFuture, AccountBinding, AuthenticatedSession,
        AuthenticationBinding, AuthorizedAccess, RequestAuthorizationError,
        ServerAccessTokenSource,
    },
    config::{MicrosoftEntraSettings, ServerSettings},
};

const TOKEN_REFRESH_MARGIN_SECONDS: u64 = 120;
const MAX_ACCOUNT_ID_BYTES: usize = 1024;

pub(crate) type NativeProviderFuture<'a, T> =
    Pin<Box<dyn Future<Output = Result<T, NativeAccessTokenProviderError>> + Send + 'a>>;

/// The only desktop authentication seam. Implementations must acquire tokens
/// in-process and return them directly to this Rust-owned connector boundary.
pub(crate) trait NativeAccessTokenProvider: Send + Sync {
    fn acquire_silent<'a>(
        &'a self,
        settings: &'a MicrosoftEntraSettings,
    ) -> NativeProviderFuture<'a, NativeAccessTokenGrant>;

    fn sign_in_interactively<'a>(
        &'a self,
        settings: &'a MicrosoftEntraSettings,
        parent_window_handle: Option<u64>,
    ) -> NativeProviderFuture<'a, NativeAccessTokenGrant>;

    fn session_status<'a>(
        &'a self,
        settings: &'a MicrosoftEntraSettings,
    ) -> NativeProviderFuture<'a, NativeAccessTokenSession>;

    fn sign_out<'a>(&'a self, settings: &'a MicrosoftEntraSettings)
        -> NativeProviderFuture<'a, ()>;
}

pub(crate) struct NativeAccessTokenGrant {
    pub(crate) access_token: Zeroizing<String>,
    pub(crate) expires_at_unix_seconds: u64,
    pub(crate) account_id: String,
}

pub(crate) struct NativeAccessTokenSession {
    pub(crate) account_id: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct NativeAccessTokenProviderError(u8);

impl NativeAccessTokenProviderError {
    pub(crate) const INTERACTION_REQUIRED: Self = Self(1);
    pub(crate) const CANCELLED: Self = Self(2);
    pub(crate) const CONFIGURATION: Self = Self(3);
    pub(crate) const POLICY_DENIED: Self = Self(4);
    pub(crate) const NETWORK: Self = Self(5);
    pub(crate) const INVALID_SESSION: Self = Self(6);
    pub(crate) const UNAVAILABLE: Self = Self(7);
}

type SettingsLoader = dyn Fn() -> Result<ServerSettings, super::config::ConfigError> + Send + Sync;
type Clock = dyn Fn() -> u64 + Send + Sync;

struct CachedAccessToken {
    configuration: MicrosoftEntraSettings,
    value: Zeroizing<String>,
    account_binding: AccountBinding,
    authentication_binding: AuthenticationBinding,
    expires_at_unix_seconds: u64,
}

impl CachedAccessToken {
    fn authorized_access(&self) -> Result<AuthorizedAccess, RequestAuthorizationError> {
        Ok(AuthorizedAccess::new(
            AccessToken::new(self.value.to_string())?,
            self.account_binding.clone(),
            self.authentication_binding.clone(),
        ))
    }
}

#[derive(Clone, PartialEq, Eq)]
struct ActiveSessionBinding {
    configuration: MicrosoftEntraSettings,
    account_binding: AccountBinding,
}

impl ActiveSessionBinding {
    fn from_cached(cached: &CachedAccessToken) -> Self {
        Self {
            configuration: cached.configuration.clone(),
            account_binding: cached.account_binding.clone(),
        }
    }
}

#[derive(Default)]
struct AccessTokenState {
    cached_token: Option<CachedAccessToken>,
    active_binding: Option<ActiveSessionBinding>,
}

impl AccessTokenState {
    fn clear(&mut self) {
        self.cached_token = None;
        self.active_binding = None;
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AccessTokenSessionStatus {
    pub(crate) configured: bool,
    pub(crate) signed_in: bool,
}

pub(super) struct NativeAccessTokenManager {
    provider: Option<Arc<dyn NativeAccessTokenProvider>>,
    settings_loader: Arc<SettingsLoader>,
    state: Mutex<AccessTokenState>,
    lifecycle: Mutex<()>,
    session: Arc<AuthenticatedSession>,
    clock: Arc<Clock>,
}

impl NativeAccessTokenManager {
    pub(super) fn discover() -> Arc<Self> {
        Arc::new(Self {
            // Production remains fail-closed until an IT-approved in-process
            // provider is selected and implemented at this boundary.
            provider: None,
            settings_loader: Arc::new(super::config::load),
            state: Mutex::new(AccessTokenState::default()),
            lifecycle: Mutex::new(()),
            session: AuthenticatedSession::new(),
            clock: Arc::new(now_unix_seconds),
        })
    }

    pub(super) fn session(&self) -> Arc<AuthenticatedSession> {
        Arc::clone(&self.session)
    }

    pub(super) fn session_is_open(&self) -> bool {
        self.session.is_open()
    }

    async fn access_token(&self) -> Result<Option<AuthorizedAccess>, RequestAuthorizationError> {
        let configuration = match self.load_configuration() {
            Ok(Some(configuration)) => configuration,
            Err(_) => {
                self.state.lock().await.clear();
                self.session.invalidate_current();
                return Err(RequestAuthorizationError::AccountChanged);
            }
            Ok(None) => {
                let mut state = self.state.lock().await;
                let account_changed = state.active_binding.is_some();
                state.clear();
                drop(state);
                if account_changed {
                    self.session.invalidate_current();
                    return Err(RequestAuthorizationError::AccountChanged);
                }
                return Ok(None);
            }
        };

        let mut state = self.state.lock().await;
        let now = (self.clock)();
        if let Some(cached) = state.cached_token.as_ref() {
            if cached.configuration == configuration
                && cached.expires_at_unix_seconds > now.saturating_add(TOKEN_REFRESH_MARGIN_SECONDS)
            {
                return cached.authorized_access().map(Some);
            }
        }

        state.cached_token = None;
        let grant = match self.provider()?.acquire_silent(&configuration).await {
            Ok(grant) => grant,
            Err(error) if error == NativeAccessTokenProviderError::INVALID_SESSION => {
                state.clear();
                drop(state);
                self.session.invalidate_current();
                return Err(RequestAuthorizationError::AccountChanged);
            }
            Err(error) => return Err(project_authorization_error(error)),
        };
        let current_configuration = match self.load_configuration() {
            Ok(current) => current,
            Err(_) => {
                state.clear();
                drop(state);
                self.session.invalidate_current();
                return Err(RequestAuthorizationError::AccountChanged);
            }
        };
        if current_configuration.as_ref() != Some(&configuration) {
            state.clear();
            drop(state);
            self.session.invalidate_current();
            return Err(RequestAuthorizationError::AccountChanged);
        }
        let accepted_at = (self.clock)();
        let cached = cache_grant(configuration, grant, accepted_at)?;
        let binding = ActiveSessionBinding::from_cached(&cached);
        if state
            .active_binding
            .as_ref()
            .is_some_and(|active| active != &binding)
        {
            state.clear();
            drop(state);
            self.session.invalidate_current();
            return Err(RequestAuthorizationError::AccountChanged);
        }
        let outbound = cached.authorized_access()?;
        state.active_binding = Some(binding);
        state.cached_token = Some(cached);
        Ok(Some(outbound))
    }

    pub(super) async fn status(&self) -> Result<AccessTokenSessionStatus, String> {
        let _lifecycle = self.lifecycle.lock().await;
        let configuration = match self.load_configuration() {
            Ok(Some(configuration)) => configuration,
            Ok(None) => {
                self.state.lock().await.clear();
                self.session.invalidate_and_wait().await;
                return Ok(AccessTokenSessionStatus {
                    configured: false,
                    signed_in: false,
                });
            }
            Err(_) => {
                self.state.lock().await.clear();
                self.session.invalidate_and_wait().await;
                return Err("Server identity configuration is unavailable.".into());
            }
        };

        let provider = match self.provider_for_ui() {
            Ok(provider) => provider,
            Err(error) => {
                self.state.lock().await.clear();
                self.session.invalidate_and_wait().await;
                return Err(error);
            }
        };
        let mut state = self.state.lock().await;
        let session = match provider.session_status(&configuration).await {
            Ok(session) => session,
            Err(error) => {
                state.clear();
                drop(state);
                self.session.invalidate_and_wait().await;
                return Err(project_provider_error(error));
            }
        };
        let current_configuration = match self.load_configuration() {
            Ok(current) => current,
            Err(_) => {
                state.clear();
                drop(state);
                self.session.invalidate_and_wait().await;
                return Err("Server identity configuration is unavailable.".into());
            }
        };
        if current_configuration.as_ref() != Some(&configuration) {
            state.clear();
            drop(state);
            self.session.invalidate_and_wait().await;
            return Err("Server identity configuration changed during status refresh.".into());
        }
        let signed_in = match session.account_id {
            Some(account_id) => {
                let current_binding = match account_binding(&account_id) {
                    Ok(binding) => binding,
                    Err(_) => {
                        state.clear();
                        drop(state);
                        self.session.invalidate_and_wait().await;
                        return Err("Microsoft Entra returned an invalid account identity.".into());
                    }
                };
                let observed = ActiveSessionBinding {
                    configuration: configuration.clone(),
                    account_binding: current_binding,
                };
                if state
                    .active_binding
                    .as_ref()
                    .is_some_and(|active| active != &observed)
                {
                    state.clear();
                    drop(state);
                    self.session.invalidate_and_wait().await;
                    return Err("Microsoft Entra account changed during the active session.".into());
                }
                state.active_binding = Some(observed);
                true
            }
            None => {
                state.clear();
                drop(state);
                self.session.invalidate_and_wait().await;
                return Ok(AccessTokenSessionStatus {
                    configured: true,
                    signed_in: false,
                });
            }
        };
        drop(state);
        Ok(AccessTokenSessionStatus {
            configured: true,
            signed_in,
        })
    }

    pub(super) async fn sign_in(&self, parent_window_handle: Option<u64>) -> Result<(), String> {
        let _lifecycle = self.lifecycle.lock().await;
        self.session.invalidate_and_wait().await;
        let mut state = self.state.lock().await;
        state.clear();
        let configuration = self
            .load_configuration()
            .map_err(|_| "Server identity configuration is unavailable.")?
            .ok_or("Configure Microsoft Entra before signing in.")?;

        let grant = self
            .provider_for_ui()?
            .sign_in_interactively(&configuration, parent_window_handle)
            .await
            .map_err(project_provider_error)?;
        if self
            .load_configuration()
            .map_err(|_| "Server identity configuration is unavailable.")?
            .as_ref()
            != Some(&configuration)
        {
            return Err("Server identity configuration changed during sign-in.".into());
        }
        let accepted_at = (self.clock)();
        let cached = cache_grant(configuration, grant, accepted_at)
            .map_err(|_| "Microsoft Entra returned an invalid sign-in response.")?;
        state.active_binding = Some(ActiveSessionBinding::from_cached(&cached));
        state.cached_token = Some(cached);
        drop(state);
        self.session.open_new_generation();
        Ok(())
    }

    pub(super) async fn sign_out(&self) -> Result<(), String> {
        let _lifecycle = self.lifecycle.lock().await;
        self.session.invalidate_and_wait().await;
        let mut state = self.state.lock().await;
        state.clear();
        let Some(configuration) = self
            .load_configuration()
            .map_err(|_| "Server identity configuration is unavailable.")?
        else {
            return Ok(());
        };

        self.provider_for_ui()?
            .sign_out(&configuration)
            .await
            .map_err(project_provider_error)
    }

    #[cfg(test)]
    pub(super) async fn configuration_changed(&self, previous: Option<&MicrosoftEntraSettings>) {
        let _lifecycle = self.lifecycle.lock().await;
        self.session.invalidate_and_wait().await;
        let mut state = self.state.lock().await;
        state.clear();
        if let (Some(provider), Some(previous)) = (self.provider.as_ref(), previous) {
            if provider.sign_out(previous).await.is_err() {
                crate::diagnostics::log(
                    "previous Microsoft Entra session cleanup is unavailable after configuration change",
                );
            }
        }
        drop(state);
        self.session.open_new_generation();
    }

    pub(super) async fn transition_configuration<T, Publish>(
        &self,
        previous: Option<&MicrosoftEntraSettings>,
        publish: Publish,
    ) -> T
    where
        Publish: FnOnce() -> (T, Option<MicrosoftEntraSettings>),
    {
        let _lifecycle = self.lifecycle.lock().await;
        self.session.invalidate_and_wait().await;
        let (result, effective_authentication) = publish();
        if previous != effective_authentication.as_ref() {
            self.state.lock().await.clear();
            if let (Some(provider), Some(previous)) = (self.provider.as_ref(), previous) {
                if provider.sign_out(previous).await.is_err() {
                    crate::diagnostics::log(
                        "previous Microsoft Entra session cleanup is unavailable after configuration change",
                    );
                }
            }
        }
        self.session.open_new_generation();
        result
    }

    fn load_configuration(
        &self,
    ) -> Result<Option<MicrosoftEntraSettings>, super::config::ConfigError> {
        (self.settings_loader)().map(|settings| settings.authentication)
    }

    fn provider(&self) -> Result<&Arc<dyn NativeAccessTokenProvider>, RequestAuthorizationError> {
        self.provider
            .as_ref()
            .ok_or(RequestAuthorizationError::Unavailable)
    }

    fn provider_for_ui(&self) -> Result<&Arc<dyn NativeAccessTokenProvider>, String> {
        self.provider
            .as_ref()
            .ok_or_else(|| project_provider_error(NativeAccessTokenProviderError::UNAVAILABLE))
    }
}

impl ServerAccessTokenSource for NativeAccessTokenManager {
    fn access(&self) -> AccessTokenFuture<'_> {
        Box::pin(self.access_token())
    }
}

fn cache_grant(
    configuration: MicrosoftEntraSettings,
    grant: NativeAccessTokenGrant,
    now: u64,
) -> Result<CachedAccessToken, RequestAuthorizationError> {
    if grant.expires_at_unix_seconds <= now.saturating_add(TOKEN_REFRESH_MARGIN_SECONDS) {
        return Err(RequestAuthorizationError::InvalidToken);
    }
    AccessToken::new(grant.access_token.to_string())?;
    let account_binding = account_binding(&grant.account_id)?;
    let authentication_binding = authentication_binding(&configuration)?;
    Ok(CachedAccessToken {
        configuration,
        value: grant.access_token,
        account_binding,
        authentication_binding,
        expires_at_unix_seconds: grant.expires_at_unix_seconds,
    })
}

fn account_binding(account_id: &str) -> Result<AccountBinding, RequestAuthorizationError> {
    if account_id.is_empty()
        || account_id.len() > MAX_ACCOUNT_ID_BYTES
        || !account_id.is_ascii()
        || account_id
            .chars()
            .any(|character| character.is_control() || character.is_whitespace())
    {
        return Err(RequestAuthorizationError::InvalidToken);
    }

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

fn authentication_binding(
    configuration: &MicrosoftEntraSettings,
) -> Result<AuthenticationBinding, RequestAuthorizationError> {
    let mut digest = Sha256::new();
    digest.update(b"yap-authentication-configuration-binding-v1\0");
    for value in [
        configuration.tenant_id.as_bytes(),
        configuration.client_id.as_bytes(),
        configuration.api_scope.as_bytes(),
    ] {
        digest.update((value.len() as u64).to_le_bytes());
        digest.update(value);
    }
    let value = digest
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    AuthenticationBinding::new(value)
}

fn now_unix_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn project_authorization_error(error: NativeAccessTokenProviderError) -> RequestAuthorizationError {
    if error == NativeAccessTokenProviderError::INVALID_SESSION {
        RequestAuthorizationError::AccountChanged
    } else {
        RequestAuthorizationError::Unavailable
    }
}

fn project_provider_error(error: NativeAccessTokenProviderError) -> String {
    match error {
        NativeAccessTokenProviderError::INTERACTION_REQUIRED => "Sign in is required.".into(),
        NativeAccessTokenProviderError::CANCELLED => "Sign-in was cancelled.".into(),
        NativeAccessTokenProviderError::CONFIGURATION => {
            "Identity provider configuration is invalid.".into()
        }
        NativeAccessTokenProviderError::POLICY_DENIED => "Sign-in was denied by policy.".into(),
        NativeAccessTokenProviderError::NETWORK => {
            "Identity provider network request failed.".into()
        }
        NativeAccessTokenProviderError::INVALID_SESSION => "Identity session is invalid.".into(),
        NativeAccessTokenProviderError::UNAVAILABLE => {
            "Approved native sign-in provider is unavailable.".into()
        }
        _ => "Approved native sign-in provider returned an unknown failure.".into(),
    }
}

#[cfg(test)]
mod tests;
