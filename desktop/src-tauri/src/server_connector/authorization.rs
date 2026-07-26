use std::{future::Future, pin::Pin, sync::Arc};

use reqwest::{
    header::{HeaderValue, AUTHORIZATION},
    RequestBuilder,
};
use zeroize::Zeroizing;

const MAX_ACCESS_TOKEN_BYTES: usize = 16 * 1024;
const DEVELOPMENT_AUTHORITY: &str = "development-loopback";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum RequestAuthorizationError {
    Unavailable,
    InvalidToken,
    AccountChanged,
}

pub(crate) struct AccessToken(Zeroizing<String>);

impl AccessToken {
    pub(crate) fn new(token: String) -> Result<Self, RequestAuthorizationError> {
        if token.is_empty()
            || token.len() > MAX_ACCESS_TOKEN_BYTES
            || !token.is_ascii()
            || token.chars().any(char::is_whitespace)
        {
            return Err(RequestAuthorizationError::InvalidToken);
        }
        Ok(Self(Zeroizing::new(token)))
    }

    fn as_str(&self) -> &str {
        self.0.as_str()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct AccountBinding(String);

impl AccountBinding {
    pub(crate) fn new(value: String) -> Result<Self, RequestAuthorizationError> {
        if value.len() != 64
            || !value
                .bytes()
                .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
        {
            return Err(RequestAuthorizationError::InvalidToken);
        }
        Ok(Self(value))
    }

    pub(crate) fn as_str(&self) -> &str {
        &self.0
    }
}

pub(crate) struct AuthorizedAccess {
    token: AccessToken,
    account_binding: AccountBinding,
}

impl AuthorizedAccess {
    pub(crate) fn new(token: AccessToken, account_binding: AccountBinding) -> Self {
        Self {
            token,
            account_binding,
        }
    }
}

pub(crate) type AccessTokenFuture<'a> = Pin<
    Box<
        dyn Future<Output = Result<Option<AuthorizedAccess>, RequestAuthorizationError>>
            + Send
            + 'a,
    >,
>;

pub(crate) trait ServerAccessTokenSource: Send + Sync {
    fn access(&self) -> AccessTokenFuture<'_>;
}

#[derive(Clone)]
enum ExpectedAccount {
    Unauthenticated,
    Authenticated(AccountBinding),
}

#[derive(Clone)]
pub(crate) struct RequestAuthorization {
    source: Arc<dyn ServerAccessTokenSource>,
    expected_account: Option<ExpectedAccount>,
}

impl RequestAuthorization {
    #[cfg(test)]
    pub(crate) fn none() -> Self {
        Self {
            source: Arc::new(NoAccessToken),
            expected_account: None,
        }
    }

    #[cfg(test)]
    pub(crate) fn fixed(token: &str) -> Self {
        Self {
            source: Arc::new(FixedAccessToken(token.to_owned())),
            expected_account: None,
        }
    }

    pub(crate) fn from_source(source: Arc<dyn ServerAccessTokenSource>) -> Self {
        Self {
            source,
            expected_account: None,
        }
    }

    pub(crate) async fn pin_current_authority(
        &self,
    ) -> Result<(Self, String), RequestAuthorizationError> {
        let account_binding = self
            .source
            .access()
            .await?
            .map(|access| access.account_binding);
        let expected_account = Some(match &account_binding {
            Some(binding) => ExpectedAccount::Authenticated(binding.clone()),
            None => ExpectedAccount::Unauthenticated,
        });
        Ok((
            Self {
                source: Arc::clone(&self.source),
                expected_account,
            },
            account_binding
                .map(|binding| binding.as_str().to_owned())
                .unwrap_or_else(|| DEVELOPMENT_AUTHORITY.to_owned()),
        ))
    }

    pub(crate) fn expect_persisted_authority(
        &self,
        authority: &str,
    ) -> Result<Self, RequestAuthorizationError> {
        let expected_account = if authority == DEVELOPMENT_AUTHORITY {
            ExpectedAccount::Unauthenticated
        } else {
            ExpectedAccount::Authenticated(AccountBinding::new(authority.to_owned())?)
        };
        Ok(Self {
            source: Arc::clone(&self.source),
            expected_account: Some(expected_account),
        })
    }

    pub(crate) async fn authorize(
        &self,
        request: RequestBuilder,
    ) -> Result<RequestBuilder, RequestAuthorizationError> {
        let access = self.source.access().await?;
        if !self.matches_expected_account(access.as_ref()) {
            return Err(RequestAuthorizationError::AccountChanged);
        }
        let Some(access) = access else {
            return Ok(request);
        };
        let bearer = Zeroizing::new(format!("Bearer {}", access.token.as_str()));
        let mut header = HeaderValue::from_str(bearer.as_str())
            .map_err(|_| RequestAuthorizationError::InvalidToken)?;
        header.set_sensitive(true);
        Ok(request.header(AUTHORIZATION, header))
    }

    fn matches_expected_account(&self, access: Option<&AuthorizedAccess>) -> bool {
        match (&self.expected_account, access) {
            (None, _) => true,
            (Some(ExpectedAccount::Unauthenticated), None) => true,
            (Some(ExpectedAccount::Authenticated(expected)), Some(actual)) => {
                expected == &actual.account_binding
            }
            _ => false,
        }
    }
}

#[cfg(test)]
struct NoAccessToken;

#[cfg(test)]
impl ServerAccessTokenSource for NoAccessToken {
    fn access(&self) -> AccessTokenFuture<'_> {
        Box::pin(async { Ok(None) })
    }
}

#[cfg(test)]
struct FixedAccessToken(String);

#[cfg(test)]
impl ServerAccessTokenSource for FixedAccessToken {
    fn access(&self) -> AccessTokenFuture<'_> {
        Box::pin(async {
            Ok(Some(AuthorizedAccess::new(
                AccessToken::new(self.0.clone())?,
                AccountBinding::new("a".repeat(64))?,
            )))
        })
    }
}

#[cfg(test)]
mod tests {
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    };

    use super::{
        AccessToken, AccessTokenFuture, AccountBinding, AuthorizedAccess, RequestAuthorization,
        RequestAuthorizationError, ServerAccessTokenSource,
    };

    struct FixedTokenSource {
        calls: AtomicUsize,
        unavailable: bool,
    }

    impl ServerAccessTokenSource for FixedTokenSource {
        fn access(&self) -> AccessTokenFuture<'_> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Box::pin(async move {
                if self.unavailable {
                    Err(RequestAuthorizationError::Unavailable)
                } else {
                    Ok(Some(AuthorizedAccess::new(
                        AccessToken::new("secret-token".to_owned())?,
                        AccountBinding::new("b".repeat(64))?,
                    )))
                }
            })
        }
    }

    struct SwitchingAccountSource {
        calls: AtomicUsize,
    }

    impl ServerAccessTokenSource for SwitchingAccountSource {
        fn access(&self) -> AccessTokenFuture<'_> {
            let call = self.calls.fetch_add(1, Ordering::SeqCst);
            Box::pin(async move {
                Ok(Some(AuthorizedAccess::new(
                    AccessToken::new("secret-token".to_owned())?,
                    AccountBinding::new(if call == 0 {
                        "a".repeat(64)
                    } else {
                        "b".repeat(64)
                    })?,
                )))
            })
        }
    }

    #[test]
    fn bearer_is_injected_once_and_marked_sensitive() {
        let source = Arc::new(FixedTokenSource {
            calls: AtomicUsize::new(0),
            unavailable: false,
        });
        let authorization = RequestAuthorization::from_source(source.clone());
        let request = tauri::async_runtime::block_on(
            authorization.authorize(reqwest::Client::new().get("https://example.invalid")),
        )
        .unwrap()
        .build()
        .unwrap();

        let header = request
            .headers()
            .get(reqwest::header::AUTHORIZATION)
            .unwrap();
        assert_eq!(header, "Bearer secret-token");
        assert!(header.is_sensitive());
        assert_eq!(source.calls.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn no_authorization_preserves_an_unauthenticated_request() {
        let request = tauri::async_runtime::block_on(
            RequestAuthorization::none()
                .authorize(reqwest::Client::new().get("https://example.invalid")),
        )
        .unwrap()
        .build()
        .unwrap();

        assert!(!request
            .headers()
            .contains_key(reqwest::header::AUTHORIZATION));
    }

    #[test]
    fn unavailable_source_fails_before_network_dispatch() {
        let source = Arc::new(FixedTokenSource {
            calls: AtomicUsize::new(0),
            unavailable: true,
        });
        let error = tauri::async_runtime::block_on(
            RequestAuthorization::from_source(source)
                .authorize(reqwest::Client::new().get("https://example.invalid")),
        )
        .unwrap_err();

        assert_eq!(error, RequestAuthorizationError::Unavailable);
    }

    #[test]
    fn invalid_tokens_are_rejected_before_header_construction() {
        assert_eq!(
            AccessToken::new("contains\nnewline".to_owned())
                .err()
                .unwrap(),
            RequestAuthorizationError::InvalidToken
        );
        assert_eq!(
            AccessToken::new(String::new()).err().unwrap(),
            RequestAuthorizationError::InvalidToken
        );
    }

    #[test]
    fn pinned_account_change_fails_before_request_dispatch() {
        let authorization = RequestAuthorization::from_source(Arc::new(SwitchingAccountSource {
            calls: AtomicUsize::new(0),
        }));
        let (pinned, authority) =
            tauri::async_runtime::block_on(authorization.pin_current_authority()).unwrap();
        assert_eq!(authority, "a".repeat(64));

        let error = tauri::async_runtime::block_on(
            pinned.authorize(reqwest::Client::new().get("https://example.invalid")),
        )
        .unwrap_err();

        assert_eq!(error, RequestAuthorizationError::AccountChanged);
    }
}
