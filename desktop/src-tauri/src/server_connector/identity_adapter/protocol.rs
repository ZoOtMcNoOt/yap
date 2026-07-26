use serde::Deserialize;
use zeroize::Zeroizing;

pub(super) const IDENTITY_ADAPTER_SCHEMA_VERSION: u16 = 1;
pub(super) const MAX_IDENTITY_ADAPTER_REQUEST_BYTES: usize = 4 * 1024;
pub(super) const MAX_IDENTITY_ADAPTER_RESPONSE_BYTES: usize = 24 * 1024;

#[derive(Debug, Clone, Copy, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(super) enum IdentityOperation {
    AcquireTokenSilent,
    SignInInteractively,
    SignOut,
    GetStatus,
}

#[derive(Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct IdentityAdapterRequest {
    pub(super) schema_version: u16,
    pub(super) request_id: String,
    pub(super) operation: IdentityOperation,
    pub(super) tenant_id: String,
    pub(super) client_id: String,
    pub(super) api_scope: String,
    pub(super) parent_window_handle: Option<u64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub(super) enum IdentityOutcome {
    Token,
    SignedIn,
    SignedOut,
    SignedInStatus,
    SignedOutStatus,
    InteractionRequired,
    Unavailable,
    InvalidRequest,
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct IdentityAdapterResponse {
    pub(super) schema_version: u16,
    pub(super) request_id: String,
    pub(super) outcome: IdentityOutcome,
    #[serde(default, deserialize_with = "deserialize_optional_secret")]
    pub(super) access_token: Option<Zeroizing<String>>,
    pub(super) expires_at_unix_seconds: Option<u64>,
    pub(super) account_id: Option<String>,
    pub(super) error_code: Option<String>,
}

fn deserialize_optional_secret<'de, D>(
    deserializer: D,
) -> Result<Option<Zeroizing<String>>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    Option::<String>::deserialize(deserializer).map(|value| value.map(Zeroizing::new))
}

impl IdentityAdapterRequest {
    pub(super) fn new(
        request_id: String,
        operation: IdentityOperation,
        settings: &super::super::config::MicrosoftEntraSettings,
        parent_window_handle: Option<u64>,
    ) -> Self {
        Self {
            schema_version: IDENTITY_ADAPTER_SCHEMA_VERSION,
            request_id,
            operation,
            tenant_id: settings.tenant_id.clone(),
            client_id: settings.client_id.clone(),
            api_scope: settings.api_scope.clone(),
            parent_window_handle,
        }
    }
}

impl IdentityAdapterResponse {
    pub(super) fn validate_for(
        &self,
        request: &IdentityAdapterRequest,
    ) -> Result<(), IdentityAdapterProtocolError> {
        if self.schema_version != IDENTITY_ADAPTER_SCHEMA_VERSION
            || self.request_id != request.request_id
        {
            return Err(IdentityAdapterProtocolError::InvalidResponse);
        }
        let identity_fields_are_valid = match self.outcome {
            IdentityOutcome::Token | IdentityOutcome::SignedIn => {
                self.access_token.is_some()
                    && self
                        .expires_at_unix_seconds
                        .is_some_and(|expires_at| expires_at > 0)
                    && self.account_id.as_deref().is_some_and(valid_account_id)
            }
            IdentityOutcome::SignedInStatus => {
                self.access_token.is_none()
                    && self.expires_at_unix_seconds.is_none()
                    && self.account_id.as_deref().is_some_and(valid_account_id)
            }
            _ => {
                self.access_token.is_none()
                    && self.expires_at_unix_seconds.is_none()
                    && self.account_id.is_none()
            }
        };
        if !identity_fields_are_valid
            || self
                .error_code
                .as_deref()
                .is_some_and(|code| !valid_error_code(code))
        {
            return Err(IdentityAdapterProtocolError::InvalidResponse);
        }
        Ok(())
    }
}

fn valid_account_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 1024
        && value.is_ascii()
        && value
            .chars()
            .all(|character| !character.is_control() && !character.is_whitespace())
}

fn valid_error_code(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'_')
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum IdentityAdapterProtocolError {
    Unavailable,
    TimedOut,
    InvalidResponse,
}
