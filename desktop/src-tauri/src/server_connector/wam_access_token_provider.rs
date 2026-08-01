//! Windows Web Account Manager as the in-process token provider.
//!
//! WAM is the broker the operating system already uses for the work account on
//! a managed machine. It matters here for one reason beyond convenience: the
//! refresh token stays inside Windows. Nothing durable is ever handed to this
//! process, so a signed-in session survives restarts without the application
//! owning a credential store, and the invariant that access tokens live only in
//! zeroizing Rust memory holds unchanged.
//!
//! Every WinRT call runs on a blocking worker. The objects involved are
//! apartment-bound and not `Send`, so they are created, used, and dropped
//! inside one thread; only owned strings cross in and a plain grant crosses
//! out. That is what lets the futures this returns stay `Send`.

use windows::core::HSTRING;
use windows::Security::Authentication::Web::Core::{
    WebAuthenticationCoreManager, WebTokenRequest, WebTokenRequestStatus,
};
use windows::Security::Credentials::WebAccountProvider;
use windows::Win32::System::Com::{CoInitializeEx, COINIT_MULTITHREADED};

use super::config::MicrosoftEntraSettings;
use super::native_access_token_provider::{
    NativeAccessTokenGrant, NativeAccessTokenProvider, NativeAccessTokenProviderError,
    NativeAccessTokenSession, NativeProviderFuture,
};

/// The Microsoft account authority WAM resolves work and school accounts
/// through. Not a URL that is fetched; it is the provider's identifier.
const MICROSOFT_PROVIDER_ID: &str = "https://login.microsoft.com";

/// Tenant-scoped sign-in. The tenant guid goes here rather than into the scope,
/// which is what keeps a personal Microsoft account from satisfying a work
/// sign-in.
fn authority_for(settings: &MicrosoftEntraSettings) -> String {
    settings.tenant_id.clone()
}

pub(super) struct WamAccessTokenProvider;

impl WamAccessTokenProvider {
    pub(super) fn new() -> Self {
        Self
    }
}

impl NativeAccessTokenProvider for WamAccessTokenProvider {
    fn acquire_silent<'a>(
        &'a self,
        settings: &'a MicrosoftEntraSettings,
    ) -> NativeProviderFuture<'a, NativeAccessTokenGrant> {
        let settings = settings.clone();
        Box::pin(async move { on_worker(move || acquire_silent_blocking(&settings)).await })
    }

    fn sign_in_interactively<'a>(
        &'a self,
        settings: &'a MicrosoftEntraSettings,
        parent_window_handle: Option<u64>,
    ) -> NativeProviderFuture<'a, NativeAccessTokenGrant> {
        let settings = settings.clone();
        Box::pin(async move {
            let _ = parent_window_handle;
            // Deliberately not implemented yet. Returning INTERACTION_REQUIRED
            // is the honest answer: silent acquisition is wired, interactive
            // sign-in is not, and the caller already treats this as "the user
            // must act". Claiming UNAVAILABLE would instead read as "no
            // provider", which is no longer true.
            let _ = settings;
            Err(NativeAccessTokenProviderError::INTERACTION_REQUIRED)
        })
    }

    fn session_status<'a>(
        &'a self,
        settings: &'a MicrosoftEntraSettings,
    ) -> NativeProviderFuture<'a, NativeAccessTokenSession> {
        let settings = settings.clone();
        Box::pin(async move { on_worker(move || session_status_blocking(&settings)).await })
    }

    fn sign_out<'a>(
        &'a self,
        settings: &'a MicrosoftEntraSettings,
    ) -> NativeProviderFuture<'a, ()> {
        let settings = settings.clone();
        Box::pin(async move {
            let _ = settings;
            // Nothing durable is held by this process, so there is nothing here
            // to clear. Signing the account out of Windows itself is the
            // operating system's affair, not this application's.
            Ok(())
        })
    }
}

/// Runs a WinRT call away from the async runtime. A worker that vanishes is
/// reported as UNAVAILABLE rather than silently succeeding.
async fn on_worker<T, F>(work: F) -> Result<T, NativeAccessTokenProviderError>
where
    T: Send + 'static,
    F: FnOnce() -> Result<T, NativeAccessTokenProviderError> + Send + 'static,
{
    match tauri::async_runtime::spawn_blocking(work).await {
        Ok(result) => result,
        Err(_) => Err(NativeAccessTokenProviderError::UNAVAILABLE),
    }
}

/// WinRT needs an initialized apartment on whatever thread touches it, and a
/// blocking-pool thread is not initialized for us. Re-initialization on a
/// thread that already has a compatible apartment is not an error.
fn ensure_apartment() {
    unsafe {
        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
    }
}

fn provider_for(
    settings: &MicrosoftEntraSettings,
) -> Result<WebAccountProvider, NativeAccessTokenProviderError> {
    WebAuthenticationCoreManager::FindAccountProviderWithAuthorityAsync(
        &HSTRING::from(MICROSOFT_PROVIDER_ID),
        &HSTRING::from(authority_for(settings)),
    )
    .and_then(|operation| operation.get())
    // A missing provider means the broker is absent or the machine has no work
    // account plugin, which is an environment fact rather than a bad token.
    .map_err(|_| NativeAccessTokenProviderError::UNAVAILABLE)
}

fn request_for(
    settings: &MicrosoftEntraSettings,
    provider: &WebAccountProvider,
) -> Result<WebTokenRequest, NativeAccessTokenProviderError> {
    let request = WebTokenRequest::Create(
        provider,
        &HSTRING::from(settings.api_scope.clone()),
        &HSTRING::from(settings.client_id.clone()),
    )
    .map_err(|_| NativeAccessTokenProviderError::CONFIGURATION)?;
    Ok(request)
}

fn acquire_silent_blocking(
    settings: &MicrosoftEntraSettings,
) -> Result<NativeAccessTokenGrant, NativeAccessTokenProviderError> {
    ensure_apartment();
    let provider = provider_for(settings)?;
    let request = request_for(settings, &provider)?;

    let result = WebAuthenticationCoreManager::GetTokenSilentlyAsync(&request)
        .and_then(|operation| operation.get())
        .map_err(|_| NativeAccessTokenProviderError::NETWORK)?;

    let status = result
        .ResponseStatus()
        .map_err(|_| NativeAccessTokenProviderError::UNAVAILABLE)?;
    classify(status)?;

    let responses = result
        .ResponseData()
        .map_err(|_| NativeAccessTokenProviderError::UNAVAILABLE)?;
    let response = responses
        .GetAt(0)
        .map_err(|_| NativeAccessTokenProviderError::INVALID_SESSION)?;

    let token = response
        .Token()
        .map_err(|_| NativeAccessTokenProviderError::INVALID_SESSION)?
        .to_string_lossy();
    if token.is_empty() {
        return Err(NativeAccessTokenProviderError::INVALID_SESSION);
    }

    let account_id = response
        .WebAccount()
        .and_then(|account| account.Id())
        .map(|id| id.to_string_lossy())
        .map_err(|_| NativeAccessTokenProviderError::INVALID_SESSION)?;

    let expires_at_unix_seconds = expiry_from_token(&token);
    Ok(NativeAccessTokenGrant {
        access_token: zeroize::Zeroizing::new(token),
        expires_at_unix_seconds,
        account_id,
    })
}

/// The token's own `exp` claim, which is authoritative and always present on
/// an Entra access token. WAM also exposes an `expiresOn` response property,
/// but it is optional and provider-specific, so trusting it would make caching
/// depend on a detail we cannot verify without a live tenant. The claim can be
/// checked offline.
///
/// Zero on failure. The connector caches only while
/// `expires_at_unix_seconds > now + margin`, so zero means "re-acquire every
/// time": slow and safe, rather than serving a token whose lifetime is unknown.
fn expiry_from_token(token: &str) -> u64 {
    let Some(payload) = token.split('.').nth(1) else {
        return 0;
    };
    let Some(decoded) = decode_base64url(payload) else {
        return 0;
    };
    serde_json::from_slice::<serde_json::Value>(&decoded)
        .ok()
        .and_then(|claims| claims.get("exp").and_then(serde_json::Value::as_u64))
        .unwrap_or(0)
}

/// JWT payloads are base64url without padding. Hand-rolled rather than adding a
/// dependency for twenty lines, which would also mean regenerating the
/// byte-compared shipped dependency inventory.
fn decode_base64url(value: &str) -> Option<Vec<u8>> {
    let mut out = Vec::with_capacity(value.len() * 3 / 4);
    let mut accumulator: u32 = 0;
    let mut bits: u32 = 0;
    for byte in value.bytes() {
        let sextet = match byte {
            b'A'..=b'Z' => byte - b'A',
            b'a'..=b'z' => byte - b'a' + 26,
            b'0'..=b'9' => byte - b'0' + 52,
            b'-' => 62,
            b'_' => 63,
            b'=' => break,
            _ => return None,
        } as u32;
        accumulator = (accumulator << 6) | sextet;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push((accumulator >> bits) as u8);
        }
    }
    // Leftover bits must be zero padding; anything else is a malformed payload
    // rather than a short one.
    if bits > 0 && (accumulator & ((1 << bits) - 1)) != 0 {
        return None;
    }
    Some(out)
}

fn session_status_blocking(
    settings: &MicrosoftEntraSettings,
) -> Result<NativeAccessTokenSession, NativeAccessTokenProviderError> {
    ensure_apartment();
    let provider = provider_for(settings)?;
    let accounts = WebAuthenticationCoreManager::FindAllAccountsAsync(&provider)
        .and_then(|operation| operation.get())
        .map_err(|_| NativeAccessTokenProviderError::UNAVAILABLE)?;

    let account_id = accounts
        .Accounts()
        .ok()
        .and_then(|list| list.GetAt(0).ok())
        .and_then(|account| account.Id().ok())
        .map(|id| id.to_string_lossy());

    Ok(NativeAccessTokenSession { account_id })
}

/// Maps WAM's response status onto the connector's error vocabulary. The
/// distinction that matters is interaction-required, which is recoverable by
/// asking the user, versus everything else, which is not.
fn classify(status: WebTokenRequestStatus) -> Result<(), NativeAccessTokenProviderError> {
    match status {
        WebTokenRequestStatus::Success => Ok(()),
        WebTokenRequestStatus::UserInteractionRequired => {
            Err(NativeAccessTokenProviderError::INTERACTION_REQUIRED)
        }
        WebTokenRequestStatus::UserCancel => Err(NativeAccessTokenProviderError::CANCELLED),
        WebTokenRequestStatus::AccountSwitch => {
            Err(NativeAccessTokenProviderError::INVALID_SESSION)
        }
        WebTokenRequestStatus::AccountProviderNotAvailable => {
            Err(NativeAccessTokenProviderError::UNAVAILABLE)
        }
        WebTokenRequestStatus::ProviderError => Err(NativeAccessTokenProviderError::POLICY_DENIED),
        _ => Err(NativeAccessTokenProviderError::UNAVAILABLE),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // The distinction that decides the header affordance in the workspace
    // header: interaction-required is the one state a user can act on, so it
    // must never be folded into the generic unavailable case.
    #[test]
    fn interaction_required_stays_distinct_from_unavailable() {
        assert_eq!(
            classify(WebTokenRequestStatus::UserInteractionRequired),
            Err(NativeAccessTokenProviderError::INTERACTION_REQUIRED)
        );
        assert_eq!(
            classify(WebTokenRequestStatus::AccountProviderNotAvailable),
            Err(NativeAccessTokenProviderError::UNAVAILABLE)
        );
        assert_eq!(classify(WebTokenRequestStatus::Success), Ok(()));
    }

    // An account switch invalidates the cached binding rather than merely
    // needing a retry, and a provider error is a policy answer, not a network
    // blip. Collapsing either into NETWORK would make the connector retry
    // something that will never succeed.
    #[test]
    fn non_recoverable_statuses_are_not_reported_as_retryable() {
        assert_eq!(
            classify(WebTokenRequestStatus::AccountSwitch),
            Err(NativeAccessTokenProviderError::INVALID_SESSION)
        );
        assert_eq!(
            classify(WebTokenRequestStatus::ProviderError),
            Err(NativeAccessTokenProviderError::POLICY_DENIED)
        );
        assert_eq!(
            classify(WebTokenRequestStatus::UserCancel),
            Err(NativeAccessTokenProviderError::CANCELLED)
        );
    }

    // An unknown future status must fail closed. WebTokenRequestStatus is a
    // WinRT enum, so a newer Windows can hand back a value this build has
    // never seen.
    #[test]
    fn an_unrecognized_status_fails_closed() {
        assert_eq!(
            classify(WebTokenRequestStatus(9999)),
            Err(NativeAccessTokenProviderError::UNAVAILABLE)
        );
    }

    // Real Entra shape: three dot-separated parts, unpadded base64url payload.
    const SAMPLE_TOKEN: &str =
        "eyJhbGciOiJSUzI1NiJ9.eyJleHAiOjE3ODU1NTE4NDAsImF1ZCI6ImFwaTovL3lhcCIsInRpZCI6InQifQ.c2ln";

    #[test]
    fn the_expiry_comes_from_the_token_claim() {
        assert_eq!(expiry_from_token(SAMPLE_TOKEN), 1_785_551_840);
    }

    // Every one of these must yield zero rather than a wrong lifetime: the
    // connector caches while expiry is in the future, so a fabricated value
    // would keep serving a token nobody can vouch for.
    #[test]
    fn an_unreadable_token_reports_no_lifetime_rather_than_guessing() {
        assert_eq!(expiry_from_token(""), 0);
        assert_eq!(expiry_from_token("notajwt"), 0);
        assert_eq!(expiry_from_token("header.!!!invalid!!!.sig"), 0);
        assert_eq!(
            expiry_from_token("header.eyJhIjoxfQ.sig"),
            0,
            "no exp claim"
        );
        assert_eq!(
            expiry_from_token("header.eyJleHAiOiJub3QtYS1udW1iZXIifQ.sig"),
            0,
            "exp present but not a number"
        );
    }

    #[test]
    fn base64url_decodes_the_unpadded_url_alphabet() {
        assert_eq!(decode_base64url("").unwrap(), b"");
        assert_eq!(decode_base64url("QQ").unwrap(), b"A");
        assert_eq!(decode_base64url("QUI").unwrap(), b"AB");
        assert_eq!(decode_base64url("QUJD").unwrap(), b"ABC");
        // 0xFB 0xFF exercises the two characters standard base64 spells + and /
        assert_eq!(decode_base64url("-_8").unwrap(), vec![0xfb, 0xff]);
        assert!(decode_base64url("has space").is_none());
        assert!(decode_base64url("plus+slash/").is_none());
    }

    // The tenant belongs in the authority, not the scope. Sending "common"
    // here would let a personal Microsoft account satisfy a work sign-in.
    #[test]
    fn the_authority_carries_the_tenant() {
        let settings = MicrosoftEntraSettings {
            tenant_id: "11111111-2222-3333-4444-555555555555".into(),
            client_id: "client".into(),
            api_scope: "api://yap/.default".into(),
        };
        assert_eq!(authority_for(&settings), settings.tenant_id);
        assert_ne!(authority_for(&settings), "common");
    }
}
