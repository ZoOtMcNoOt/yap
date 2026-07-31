use std::{
    future::Future,
    pin::Pin,
    sync::{
        atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering},
        Arc, Mutex,
    },
};

use reqwest::{
    header::{HeaderValue, AUTHORIZATION},
    Client, IntoUrl, RequestBuilder, StatusCode, Url,
};
use tokio::sync::{watch, Notify};
use zeroize::Zeroizing;

mod live_websocket;

pub use live_websocket::{
    AuthenticatedLiveConnection, AuthenticatedLiveError, AuthenticatedLiveMessage,
};

const MAX_ACCESS_TOKEN_BYTES: usize = 16 * 1024;
const DEVELOPMENT_AUTHORITY: &str = "development-loopback";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum RequestAuthorizationError {
    Unavailable,
    InvalidToken,
    AccountChanged,
}

#[derive(Debug)]
pub(crate) enum AuthenticatedDispatchError {
    Authorization(RequestAuthorizationError),
    Transport(reqwest::Error),
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct AuthenticationBinding(String);

impl AuthenticationBinding {
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
    authentication_binding: AuthenticationBinding,
}

impl AuthorizedAccess {
    pub(crate) fn new(
        token: AccessToken,
        account_binding: AccountBinding,
        authentication_binding: AuthenticationBinding,
    ) -> Self {
        Self {
            token,
            account_binding,
            authentication_binding,
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
enum ExpectedAuthority {
    Unauthenticated,
    Authenticated {
        account: AccountBinding,
        authentication: AuthenticationBinding,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct PinnedRemoteAuthority {
    account: String,
    authentication: String,
}

impl PinnedRemoteAuthority {
    pub(crate) fn account(&self) -> &str {
        &self.account
    }

    pub(crate) fn authentication(&self) -> &str {
        &self.authentication
    }
}

#[derive(Clone)]
struct RequestAuthorization {
    source: Arc<dyn ServerAccessTokenSource>,
    expected_authority: Option<ExpectedAuthority>,
}

impl RequestAuthorization {
    fn from_source(source: Arc<dyn ServerAccessTokenSource>) -> Self {
        Self {
            source,
            expected_authority: None,
        }
    }

    async fn pin_current_authority(
        &self,
    ) -> Result<(Self, PinnedRemoteAuthority), RequestAuthorizationError> {
        let access = self.source.access().await?;
        let expected_authority = Some(match &access {
            Some(access) => ExpectedAuthority::Authenticated {
                account: access.account_binding.clone(),
                authentication: access.authentication_binding.clone(),
            },
            None => ExpectedAuthority::Unauthenticated,
        });
        let authority = match access {
            Some(access) => PinnedRemoteAuthority {
                account: access.account_binding.as_str().to_owned(),
                authentication: access.authentication_binding.as_str().to_owned(),
            },
            None => PinnedRemoteAuthority {
                account: DEVELOPMENT_AUTHORITY.to_owned(),
                authentication: DEVELOPMENT_AUTHORITY.to_owned(),
            },
        };
        Ok((
            Self {
                source: Arc::clone(&self.source),
                expected_authority,
            },
            authority,
        ))
    }

    fn expect_persisted_authority(
        &self,
        account: &str,
        authentication: &str,
    ) -> Result<Self, RequestAuthorizationError> {
        let expected_authority =
            if account == DEVELOPMENT_AUTHORITY && authentication == DEVELOPMENT_AUTHORITY {
                ExpectedAuthority::Unauthenticated
            } else if account == DEVELOPMENT_AUTHORITY || authentication == DEVELOPMENT_AUTHORITY {
                return Err(RequestAuthorizationError::InvalidToken);
            } else {
                ExpectedAuthority::Authenticated {
                    account: AccountBinding::new(account.to_owned())?,
                    authentication: AuthenticationBinding::new(authentication.to_owned())?,
                }
            };
        Ok(Self {
            source: Arc::clone(&self.source),
            expected_authority: Some(expected_authority),
        })
    }

    async fn authorize(
        &self,
        request: RequestBuilder,
    ) -> Result<RequestBuilder, RequestAuthorizationError> {
        let access = self.source.access().await?;
        if !self.matches_expected_authority(access.as_ref()) {
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

    fn matches_expected_authority(&self, access: Option<&AuthorizedAccess>) -> bool {
        match (&self.expected_authority, access) {
            (None, _) => true,
            (Some(ExpectedAuthority::Unauthenticated), None) => true,
            (
                Some(ExpectedAuthority::Authenticated {
                    account,
                    authentication,
                }),
                Some(actual),
            ) => {
                account == &actual.account_binding
                    && authentication == &actual.authentication_binding
            }
            _ => false,
        }
    }
}

#[derive(Debug)]
struct SessionGeneration {
    id: u64,
    cancelled: AtomicBool,
    active_leases: AtomicUsize,
    cancelled_tx: watch::Sender<bool>,
    drained_notify: Notify,
}

impl SessionGeneration {
    fn new(id: u64) -> Self {
        let (cancelled_tx, _) = watch::channel(false);
        Self {
            id,
            cancelled: AtomicBool::new(false),
            active_leases: AtomicUsize::new(0),
            cancelled_tx,
            drained_notify: Notify::new(),
        }
    }

    fn cancel(&self) {
        if !self.cancelled.swap(true, Ordering::AcqRel) {
            self.cancelled_tx.send_replace(true);
        }
    }

    async fn cancelled(&self) {
        let mut cancelled = self.cancelled_tx.subscribe();
        loop {
            if *cancelled.borrow_and_update() {
                return;
            }
            if cancelled.changed().await.is_err() {
                return;
            }
        }
    }

    async fn wait_until_drained(&self) {
        loop {
            let notified = self.drained_notify.notified();
            if self.active_leases.load(Ordering::Acquire) == 0 {
                return;
            }
            notified.await;
        }
    }
}

#[derive(Debug)]
pub(super) struct AuthenticatedSession {
    current: Mutex<Option<Arc<SessionGeneration>>>,
    next_generation: AtomicU64,
}

impl AuthenticatedSession {
    pub(super) fn new() -> Arc<Self> {
        let initial = Arc::new(SessionGeneration::new(1));
        Arc::new(Self {
            current: Mutex::new(Some(initial)),
            next_generation: AtomicU64::new(1),
        })
    }

    #[cfg(test)]
    fn acquire(self: &Arc<Self>) -> Result<SessionLease, RequestAuthorizationError> {
        self.acquire_expected(None)
    }

    fn acquire_expected(
        self: &Arc<Self>,
        expected_generation: Option<u64>,
    ) -> Result<SessionLease, RequestAuthorizationError> {
        let current = self.current.lock().expect("authenticated session poisoned");
        let generation = current
            .as_ref()
            .filter(|generation| !generation.cancelled.load(Ordering::Acquire))
            .filter(|generation| {
                expected_generation.is_none_or(|expected| generation.id == expected)
            })
            .cloned()
            .ok_or_else(|| {
                if expected_generation.is_some() {
                    RequestAuthorizationError::AccountChanged
                } else {
                    RequestAuthorizationError::Unavailable
                }
            })?;
        generation.active_leases.fetch_add(1, Ordering::AcqRel);
        Ok(SessionLease {
            session: Arc::clone(self),
            generation,
        })
    }

    pub(super) fn invalidate_current(&self) {
        if let Some(generation) = self
            .current
            .lock()
            .expect("authenticated session poisoned")
            .as_ref()
            .cloned()
        {
            generation.cancel();
        }
    }

    pub(super) async fn invalidate_and_wait(&self) {
        if let Some(generation) = self.take_current() {
            generation.cancel();
            generation.wait_until_drained().await;
        }
    }

    pub(super) fn open_new_generation(&self) {
        let id = self.next_generation.fetch_add(1, Ordering::AcqRel) + 1;
        let replacement = Arc::new(SessionGeneration::new(id));
        let previous = self
            .current
            .lock()
            .expect("authenticated session poisoned")
            .replace(replacement);
        if let Some(previous) = previous {
            previous.cancel();
        }
    }

    fn take_current(&self) -> Option<Arc<SessionGeneration>> {
        self.current
            .lock()
            .expect("authenticated session poisoned")
            .take()
    }

    fn invalidate_if_current(&self, expected: &Arc<SessionGeneration>) {
        let generation = {
            let current = self.current.lock().expect("authenticated session poisoned");
            if current
                .as_ref()
                .is_some_and(|actual| Arc::ptr_eq(actual, expected))
            {
                current.as_ref().cloned()
            } else {
                None
            }
        };
        if let Some(generation) = generation {
            generation.cancel();
        }
    }

    fn is_current(&self, expected: &Arc<SessionGeneration>) -> bool {
        !expected.cancelled.load(Ordering::Acquire)
            && self
                .current
                .lock()
                .expect("authenticated session poisoned")
                .as_ref()
                .is_some_and(|actual| actual.id == expected.id && Arc::ptr_eq(actual, expected))
    }

    pub(super) fn is_open(&self) -> bool {
        self.current
            .lock()
            .expect("authenticated session poisoned")
            .as_ref()
            .is_some_and(|generation| !generation.cancelled.load(Ordering::Acquire))
    }

    fn current_generation_id(&self) -> Result<u64, RequestAuthorizationError> {
        self.current
            .lock()
            .expect("authenticated session poisoned")
            .as_ref()
            .filter(|generation| !generation.cancelled.load(Ordering::Acquire))
            .map(|generation| generation.id)
            .ok_or(RequestAuthorizationError::Unavailable)
    }
}

#[derive(Debug)]
struct SessionLease {
    session: Arc<AuthenticatedSession>,
    generation: Arc<SessionGeneration>,
}

impl SessionLease {
    async fn cancelled(&self) {
        self.generation.cancelled().await;
    }

    fn ensure_current(&self) -> Result<(), RequestAuthorizationError> {
        if self.session.is_current(&self.generation) {
            Ok(())
        } else {
            Err(RequestAuthorizationError::AccountChanged)
        }
    }

    fn invalidate_generation(&self) {
        self.session.invalidate_if_current(&self.generation);
    }

    #[cfg(test)]
    fn generation(&self) -> u64 {
        self.generation.id
    }
}

impl Drop for SessionLease {
    fn drop(&mut self) {
        let previous = self.generation.active_leases.fetch_sub(1, Ordering::AcqRel);
        debug_assert!(previous > 0, "session lease count underflow");
        if previous == 1 {
            self.generation.drained_notify.notify_one();
        }
    }
}

#[derive(Clone)]
pub(crate) struct AuthenticatedRequestDispatcher {
    client: Client,
    live_client: Client,
    authorization: RequestAuthorization,
    session: Arc<AuthenticatedSession>,
    connector_generation: Option<Arc<AtomicU64>>,
    dispatch_binding: Option<AuthenticatedDispatchBinding>,
}

#[derive(Clone)]
struct AuthenticatedDispatchBinding {
    connector_generation: u64,
    session_generation: u64,
    origin: String,
}

impl AuthenticatedRequestDispatcher {
    pub(super) fn from_source(
        client: Client,
        source: Arc<dyn ServerAccessTokenSource>,
        session: Arc<AuthenticatedSession>,
    ) -> Self {
        Self {
            client,
            live_client: live_websocket::bounded_live_client()
                .expect("bounded live server connector client must build"),
            authorization: RequestAuthorization::from_source(source),
            session,
            connector_generation: None,
            dispatch_binding: None,
        }
    }

    pub(super) fn with_connector_generation(
        mut self,
        connector_generation: Arc<AtomicU64>,
    ) -> Self {
        self.connector_generation = Some(connector_generation);
        self
    }

    pub(crate) fn bind_current_transport(
        &self,
        connector_generation: u64,
        origin: &str,
    ) -> Result<Self, RequestAuthorizationError> {
        let current_connector_generation = self
            .connector_generation
            .as_ref()
            .ok_or(RequestAuthorizationError::Unavailable)?;
        if current_connector_generation.load(Ordering::Acquire) != connector_generation {
            return Err(RequestAuthorizationError::Unavailable);
        }
        let origin = canonical_authorization_origin(
            &Url::parse(origin).map_err(|_| RequestAuthorizationError::Unavailable)?,
        )?;
        Ok(Self {
            client: self.client.clone(),
            live_client: self.live_client.clone(),
            authorization: self.authorization.clone(),
            session: Arc::clone(&self.session),
            connector_generation: self.connector_generation.clone(),
            dispatch_binding: Some(AuthenticatedDispatchBinding {
                connector_generation,
                session_generation: self.session.current_generation_id()?,
                origin,
            }),
        })
    }

    #[cfg(test)]
    pub(crate) fn unauthenticated(client: Client) -> Self {
        Self::from_source(client, Arc::new(NoAccessToken), AuthenticatedSession::new())
    }

    #[cfg(test)]
    pub(crate) fn fixed(client: Client, token: &str) -> Self {
        Self::fixed_authority(client, token, &"a".repeat(64), &"b".repeat(64))
    }

    #[cfg(test)]
    pub(crate) fn fixed_authority(
        client: Client,
        token: &str,
        account: &str,
        authentication: &str,
    ) -> Self {
        Self::from_source(
            client,
            Arc::new(FixedAccessToken {
                token: token.to_owned(),
                account: account.to_owned(),
                authentication: authentication.to_owned(),
            }),
            AuthenticatedSession::new(),
        )
    }

    pub(crate) fn get<U: IntoUrl>(&self, url: U) -> RequestBuilder {
        self.client.get(url)
    }

    pub(crate) fn post<U: IntoUrl>(&self, url: U) -> RequestBuilder {
        self.client.post(url)
    }

    pub(crate) fn put<U: IntoUrl>(&self, url: U) -> RequestBuilder {
        self.client.put(url)
    }

    pub(crate) fn delete<U: IntoUrl>(&self, url: U) -> RequestBuilder {
        self.client.delete(url)
    }

    pub(crate) async fn pin_current_authority(
        &self,
    ) -> Result<(Self, PinnedRemoteAuthority), RequestAuthorizationError> {
        self.ensure_connector_current()?;
        let lease = self.acquire_dispatch_lease()?;
        let result = tokio::select! {
            biased;
            _ = lease.cancelled() => return Err(RequestAuthorizationError::AccountChanged),
            result = self.authorization.pin_current_authority() => result,
        };
        let (authorization, authority) = match result {
            Ok(pinned) => pinned,
            Err(error) => {
                if error == RequestAuthorizationError::AccountChanged {
                    lease.invalidate_generation();
                }
                return Err(error);
            }
        };
        self.ensure_connector_current()?;
        lease.ensure_current()?;
        Ok((
            Self {
                client: self.client.clone(),
                live_client: self.live_client.clone(),
                authorization,
                session: Arc::clone(&self.session),
                connector_generation: self.connector_generation.clone(),
                dispatch_binding: self.dispatch_binding.clone(),
            },
            authority,
        ))
    }

    pub(crate) fn expect_persisted_authority(
        &self,
        account: &str,
        authentication: &str,
    ) -> Result<Self, RequestAuthorizationError> {
        Ok(Self {
            client: self.client.clone(),
            live_client: self.live_client.clone(),
            authorization: self
                .authorization
                .expect_persisted_authority(account, authentication)?,
            session: Arc::clone(&self.session),
            connector_generation: self.connector_generation.clone(),
            dispatch_binding: self.dispatch_binding.clone(),
        })
    }

    pub(crate) async fn send(
        &self,
        request: RequestBuilder,
    ) -> Result<AuthenticatedResponse, AuthenticatedDispatchError> {
        self.ensure_bound_request(&request)
            .map_err(AuthenticatedDispatchError::Authorization)?;
        let lease = self
            .acquire_dispatch_lease()
            .map_err(AuthenticatedDispatchError::Authorization)?;
        let authorized = tokio::select! {
            biased;
            _ = lease.cancelled() => {
                return Err(AuthenticatedDispatchError::Authorization(
                    RequestAuthorizationError::AccountChanged,
                ));
            }
            result = self.authorization.authorize(request) => result,
        };
        let authorized = match authorized {
            Ok(request) => request,
            Err(error) => {
                if error == RequestAuthorizationError::AccountChanged {
                    lease.invalidate_generation();
                }
                return Err(AuthenticatedDispatchError::Authorization(error));
            }
        };
        self.ensure_bound_request(&authorized)
            .map_err(AuthenticatedDispatchError::Authorization)?;
        lease
            .ensure_current()
            .map_err(AuthenticatedDispatchError::Authorization)?;

        let response = tokio::select! {
            biased;
            _ = lease.cancelled() => {
                return Err(AuthenticatedDispatchError::Authorization(
                    RequestAuthorizationError::AccountChanged,
                ));
            }
            result = authorized.send() => {
                result.map_err(AuthenticatedDispatchError::Transport)?
            }
        };
        lease
            .ensure_current()
            .map_err(AuthenticatedDispatchError::Authorization)?;
        Ok(AuthenticatedResponse { response, lease })
    }

    fn acquire_dispatch_lease(&self) -> Result<SessionLease, RequestAuthorizationError> {
        self.session.acquire_expected(
            self.dispatch_binding
                .as_ref()
                .map(|binding| binding.session_generation),
        )
    }

    fn ensure_connector_current(&self) -> Result<(), RequestAuthorizationError> {
        let Some(binding) = self.dispatch_binding.as_ref() else {
            return Ok(());
        };
        if self
            .connector_generation
            .as_ref()
            .is_some_and(|current| current.load(Ordering::Acquire) == binding.connector_generation)
        {
            Ok(())
        } else {
            Err(RequestAuthorizationError::Unavailable)
        }
    }

    fn ensure_bound_origin(&self, url: &Url) -> Result<(), RequestAuthorizationError> {
        self.ensure_connector_current()?;
        let Some(binding) = self.dispatch_binding.as_ref() else {
            return Ok(());
        };
        if canonical_authorization_origin(url)? == binding.origin {
            Ok(())
        } else {
            Err(RequestAuthorizationError::Unavailable)
        }
    }

    fn ensure_bound_request(
        &self,
        request: &RequestBuilder,
    ) -> Result<(), RequestAuthorizationError> {
        if self.dispatch_binding.is_none() {
            return Ok(());
        }
        let request = request
            .try_clone()
            .ok_or(RequestAuthorizationError::Unavailable)?
            .build()
            .map_err(|_| RequestAuthorizationError::Unavailable)?;
        self.ensure_bound_origin(request.url())
    }
}

fn canonical_authorization_origin(url: &Url) -> Result<String, RequestAuthorizationError> {
    let mut canonical = url.clone();
    match canonical.scheme() {
        "ws" => canonical
            .set_scheme("http")
            .map_err(|_| RequestAuthorizationError::Unavailable)?,
        "wss" => canonical
            .set_scheme("https")
            .map_err(|_| RequestAuthorizationError::Unavailable)?,
        "http" | "https" => {}
        _ => return Err(RequestAuthorizationError::Unavailable),
    }
    Ok(canonical.origin().ascii_serialization())
}

#[derive(Debug)]
pub(crate) struct AuthenticatedResponse {
    response: reqwest::Response,
    lease: SessionLease,
}

impl AuthenticatedResponse {
    pub(crate) fn ensure_current(&self) -> Result<(), RequestAuthorizationError> {
        self.lease.ensure_current()
    }

    pub(crate) fn status(&self) -> Result<StatusCode, RequestAuthorizationError> {
        self.ensure_current()?;
        Ok(self.response.status())
    }

    pub(crate) fn content_length(&self) -> Result<Option<u64>, RequestAuthorizationError> {
        self.ensure_current()?;
        Ok(self.response.content_length())
    }

    pub(crate) async fn chunk(&mut self) -> Result<Option<Vec<u8>>, AuthenticatedDispatchError> {
        let lease = &self.lease;
        let response = &mut self.response;
        let chunk = tokio::select! {
            biased;
            _ = lease.cancelled() => {
                return Err(AuthenticatedDispatchError::Authorization(
                    RequestAuthorizationError::AccountChanged,
                ));
            }
            result = response.chunk() => {
                result.map_err(AuthenticatedDispatchError::Transport)?
            }
        };
        lease
            .ensure_current()
            .map_err(AuthenticatedDispatchError::Authorization)?;
        Ok(chunk.map(|chunk| chunk.to_vec()))
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
struct FixedAccessToken {
    token: String,
    account: String,
    authentication: String,
}

#[cfg(test)]
impl ServerAccessTokenSource for FixedAccessToken {
    fn access(&self) -> AccessTokenFuture<'_> {
        Box::pin(async {
            Ok(Some(AuthorizedAccess::new(
                AccessToken::new(self.token.clone())?,
                AccountBinding::new(self.account.clone())?,
                AuthenticationBinding::new(self.authentication.clone())?,
            )))
        })
    }
}

#[cfg(test)]
mod tests {
    use std::{
        net::TcpListener,
        sync::{
            atomic::{AtomicU64, AtomicUsize, Ordering},
            Arc,
        },
    };

    use super::{
        AccessToken, AccessTokenFuture, AccountBinding, AuthenticatedDispatchError,
        AuthenticatedRequestDispatcher, AuthenticatedSession, AuthenticationBinding,
        AuthorizedAccess, RequestAuthorization, RequestAuthorizationError, ServerAccessTokenSource,
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
                        AuthenticationBinding::new("c".repeat(64))?,
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
                    AuthenticationBinding::new("c".repeat(64))?,
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
        assert_eq!(authority.account(), "a".repeat(64));
        assert_eq!(authority.authentication(), "c".repeat(64));

        let error = tauri::async_runtime::block_on(
            pinned.authorize(reqwest::Client::new().get("https://example.invalid")),
        )
        .unwrap_err();

        assert_eq!(error, RequestAuthorizationError::AccountChanged);
    }

    #[test]
    fn stale_generation_is_rejected_after_a_new_session_opens() {
        let session = AuthenticatedSession::new();
        let lease = session.acquire().unwrap();
        let stale_generation = lease.generation();

        session.invalidate_current();
        session.open_new_generation();
        let fresh = session.acquire().unwrap();

        assert_ne!(stale_generation, fresh.generation());
        assert_eq!(
            lease.ensure_current(),
            Err(RequestAuthorizationError::AccountChanged)
        );
        assert!(fresh.ensure_current().is_ok());
    }

    #[test]
    fn bound_dispatch_rejects_stale_generation_and_wrong_origin_before_token_or_socket() {
        let source = Arc::new(FixedTokenSource {
            calls: AtomicUsize::new(0),
            unavailable: false,
        });
        let connector_generation = Arc::new(AtomicU64::new(7));
        let approved = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let other = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let approved_origin = format!("http://{}", approved.local_addr().unwrap());
        let other_origin = format!("http://{}", other.local_addr().unwrap());
        let dispatcher = AuthenticatedRequestDispatcher::from_source(
            reqwest::Client::new(),
            source.clone(),
            AuthenticatedSession::new(),
        )
        .with_connector_generation(Arc::clone(&connector_generation))
        .bind_current_transport(7, &approved_origin)
        .unwrap();

        assert!(matches!(
            tauri::async_runtime::block_on(
                dispatcher.send(dispatcher.get(format!("{other_origin}/protected")))
            )
            .unwrap_err(),
            AuthenticatedDispatchError::Authorization(RequestAuthorizationError::Unavailable)
        ));
        connector_generation.store(8, Ordering::Release);
        assert!(matches!(
            tauri::async_runtime::block_on(
                dispatcher.send(dispatcher.get(format!("{approved_origin}/protected")))
            )
            .unwrap_err(),
            AuthenticatedDispatchError::Authorization(RequestAuthorizationError::Unavailable)
        ));
        assert_eq!(source.calls.load(Ordering::SeqCst), 0);

        for listener in [&approved, &other] {
            listener.set_nonblocking(true).unwrap();
            assert_eq!(
                listener.accept().unwrap_err().kind(),
                std::io::ErrorKind::WouldBlock
            );
        }
    }
}
