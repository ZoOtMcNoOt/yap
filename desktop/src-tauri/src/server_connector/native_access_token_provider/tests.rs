use std::{
    io::{Read, Write},
    net::TcpListener,
    sync::{
        atomic::{AtomicU64, AtomicUsize, Ordering},
        Arc, Barrier, Mutex as StandardMutex,
    },
    thread,
    time::Duration,
};
use tungstenite::{
    accept_hdr,
    handshake::server::{Request, Response},
    http::{
        header::{AUTHORIZATION, SEC_WEBSOCKET_PROTOCOL},
        HeaderValue,
    },
    Message as ServerMessage,
};

use super::*;
use crate::server_connector::{
    authorization::{AuthenticatedDispatchError, AuthenticatedRequestDispatcher},
    client::bounded_client,
    config::CURRENT_SCHEMA_VERSION,
};

#[derive(Clone)]
struct FakeGrant {
    access_token: String,
    expires_at_unix_seconds: u64,
    account_id: String,
}

impl FakeGrant {
    fn valid() -> Self {
        Self {
            access_token: "test-token".into(),
            expires_at_unix_seconds: now_unix_seconds() + 3_600,
            account_id: "test-account.tenant".into(),
        }
    }

    fn into_native(self) -> NativeAccessTokenGrant {
        NativeAccessTokenGrant {
            access_token: Zeroizing::new(self.access_token),
            expires_at_unix_seconds: self.expires_at_unix_seconds,
            account_id: self.account_id,
        }
    }
}

#[derive(Clone)]
enum FakeSession {
    SignedIn(String),
    SignedOut,
}

#[derive(Clone)]
struct SilentGate {
    entered: Arc<tokio::sync::Notify>,
    release: Arc<tokio::sync::Notify>,
}

impl SilentGate {
    fn new() -> Self {
        Self {
            entered: Arc::new(tokio::sync::Notify::new()),
            release: Arc::new(tokio::sync::Notify::new()),
        }
    }

    async fn wait_until_entered(&self) {
        self.entered.notified().await;
    }

    fn release(&self) {
        self.release.notify_one();
    }
}

struct ProviderCallGuard<'a> {
    active: &'a AtomicUsize,
}

impl<'a> ProviderCallGuard<'a> {
    fn enter(active: &'a AtomicUsize, maximum: &AtomicUsize) -> Self {
        let concurrent = active.fetch_add(1, Ordering::SeqCst) + 1;
        maximum.fetch_max(concurrent, Ordering::SeqCst);
        Self { active }
    }
}

impl Drop for ProviderCallGuard<'_> {
    fn drop(&mut self) {
        self.active.fetch_sub(1, Ordering::SeqCst);
    }
}

struct FakeNativeAccessTokenProvider {
    silent_result: StandardMutex<Result<FakeGrant, NativeAccessTokenProviderError>>,
    interactive_result: StandardMutex<Result<FakeGrant, NativeAccessTokenProviderError>>,
    status_result: StandardMutex<Result<FakeSession, NativeAccessTokenProviderError>>,
    sign_out_result: StandardMutex<Result<(), NativeAccessTokenProviderError>>,
    silent_calls: AtomicUsize,
    interactive_calls: AtomicUsize,
    status_calls: AtomicUsize,
    sign_out_calls: AtomicUsize,
    last_parent_window_handle: AtomicU64,
    silent_delay: StandardMutex<Duration>,
    silent_gate: StandardMutex<Option<SilentGate>>,
    active_calls: AtomicUsize,
    maximum_active_calls: AtomicUsize,
}

impl FakeNativeAccessTokenProvider {
    fn valid() -> Self {
        Self {
            silent_result: StandardMutex::new(Ok(FakeGrant::valid())),
            interactive_result: StandardMutex::new(Ok(FakeGrant::valid())),
            status_result: StandardMutex::new(Ok(FakeSession::SignedIn(
                "test-account.tenant".into(),
            ))),
            sign_out_result: StandardMutex::new(Ok(())),
            silent_calls: AtomicUsize::new(0),
            interactive_calls: AtomicUsize::new(0),
            status_calls: AtomicUsize::new(0),
            sign_out_calls: AtomicUsize::new(0),
            last_parent_window_handle: AtomicU64::new(0),
            silent_delay: StandardMutex::new(Duration::ZERO),
            silent_gate: StandardMutex::new(None),
            active_calls: AtomicUsize::new(0),
            maximum_active_calls: AtomicUsize::new(0),
        }
    }

    fn with_silent_error(error: NativeAccessTokenProviderError) -> Self {
        let provider = Self::valid();
        *provider.silent_result.lock().unwrap() = Err(error);
        provider
    }

    fn set_silent_grant(&self, grant: FakeGrant) {
        *self.silent_result.lock().unwrap() = Ok(grant);
    }

    fn set_interactive_error(&self, error: NativeAccessTokenProviderError) {
        *self.interactive_result.lock().unwrap() = Err(error);
    }

    fn set_interactive_grant(&self, grant: FakeGrant) {
        *self.interactive_result.lock().unwrap() = Ok(grant);
    }

    fn set_status(&self, status: FakeSession) {
        *self.status_result.lock().unwrap() = Ok(status);
    }

    fn set_status_error(&self, error: NativeAccessTokenProviderError) {
        *self.status_result.lock().unwrap() = Err(error);
    }

    fn set_sign_out_error(&self, error: NativeAccessTokenProviderError) {
        *self.sign_out_result.lock().unwrap() = Err(error);
    }

    fn set_silent_gate(&self, gate: SilentGate) {
        *self.silent_gate.lock().unwrap() = Some(gate);
    }
}

impl NativeAccessTokenProvider for FakeNativeAccessTokenProvider {
    fn acquire_silent<'a>(
        &'a self,
        _settings: &'a MicrosoftEntraSettings,
    ) -> NativeProviderFuture<'a, NativeAccessTokenGrant> {
        self.silent_calls.fetch_add(1, Ordering::SeqCst);
        let result = self.silent_result.lock().unwrap().clone();
        let delay = *self.silent_delay.lock().unwrap();
        let gate = self.silent_gate.lock().unwrap().clone();
        Box::pin(async move {
            let _active = ProviderCallGuard::enter(&self.active_calls, &self.maximum_active_calls);
            if let Some(gate) = gate {
                gate.entered.notify_one();
                gate.release.notified().await;
            }
            if !delay.is_zero() {
                tokio::time::sleep(delay).await;
            }
            result.map(FakeGrant::into_native)
        })
    }

    fn sign_in_interactively<'a>(
        &'a self,
        _settings: &'a MicrosoftEntraSettings,
        parent_window_handle: Option<u64>,
    ) -> NativeProviderFuture<'a, NativeAccessTokenGrant> {
        self.interactive_calls.fetch_add(1, Ordering::SeqCst);
        self.last_parent_window_handle
            .store(parent_window_handle.unwrap_or_default(), Ordering::SeqCst);
        let result = self.interactive_result.lock().unwrap().clone();
        Box::pin(async move {
            let _active = ProviderCallGuard::enter(&self.active_calls, &self.maximum_active_calls);
            result.map(FakeGrant::into_native)
        })
    }

    fn session_status<'a>(
        &'a self,
        _settings: &'a MicrosoftEntraSettings,
    ) -> NativeProviderFuture<'a, NativeAccessTokenSession> {
        self.status_calls.fetch_add(1, Ordering::SeqCst);
        let result = self.status_result.lock().unwrap().clone();
        Box::pin(async move {
            let _active = ProviderCallGuard::enter(&self.active_calls, &self.maximum_active_calls);
            result.map(|status| NativeAccessTokenSession {
                account_id: match status {
                    FakeSession::SignedIn(account_id) => Some(account_id),
                    FakeSession::SignedOut => None,
                },
            })
        })
    }

    fn sign_out<'a>(
        &'a self,
        _settings: &'a MicrosoftEntraSettings,
    ) -> NativeProviderFuture<'a, ()> {
        self.sign_out_calls.fetch_add(1, Ordering::SeqCst);
        let result = *self.sign_out_result.lock().unwrap();
        Box::pin(async move {
            let _active = ProviderCallGuard::enter(&self.active_calls, &self.maximum_active_calls);
            result
        })
    }
}

fn entra_settings(seed: u8) -> MicrosoftEntraSettings {
    MicrosoftEntraSettings {
        tenant_id: format!("{seed:08x}-1111-1111-1111-111111111111"),
        client_id: format!("{seed:08x}-2222-2222-2222-222222222222"),
        api_scope: format!("api://{seed:08x}-3333-3333-3333-333333333333/access_as_user"),
    }
}

fn server_settings(authentication: Option<MicrosoftEntraSettings>) -> ServerSettings {
    ServerSettings {
        schema_version: CURRENT_SCHEMA_VERSION,
        enabled: true,
        base_url: Some("https://server.example".into()),
        authentication,
    }
}

fn manager(
    provider: Arc<FakeNativeAccessTokenProvider>,
    settings: Arc<StandardMutex<ServerSettings>>,
) -> Arc<NativeAccessTokenManager> {
    manager_with_clock(provider, settings, Arc::new(now_unix_seconds))
}

fn manager_with_clock(
    provider: Arc<FakeNativeAccessTokenProvider>,
    settings: Arc<StandardMutex<ServerSettings>>,
    clock: Arc<Clock>,
) -> Arc<NativeAccessTokenManager> {
    Arc::new(NativeAccessTokenManager {
        provider: Some(provider),
        settings_loader: Arc::new(move || Ok(settings.lock().unwrap().clone())),
        state: Mutex::new(AccessTokenState::default()),
        lifecycle: Mutex::new(()),
        session: AuthenticatedSession::new(),
        clock,
    })
}

fn dispatcher(manager: &Arc<NativeAccessTokenManager>) -> AuthenticatedRequestDispatcher {
    AuthenticatedRequestDispatcher::from_source(
        bounded_client().unwrap(),
        manager.clone(),
        manager.session(),
    )
}

#[test]
fn silent_tokens_are_cached_and_only_reach_the_request_authorizer() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(provider.clone(), settings);
    let authenticated = dispatcher(&manager);
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let server = thread::spawn(move || {
        for _ in 0..2 {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0_u8; 2048];
            let read = stream.read(&mut request).unwrap();
            let request = String::from_utf8_lossy(&request[..read]).to_ascii_lowercase();
            assert!(request.contains("authorization: bearer test-token\r\n"));
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                .unwrap();
        }
    });

    for _ in 0..2 {
        let response = tauri::async_runtime::block_on(
            authenticated.send(authenticated.get(format!("http://{address}/protected"))),
        )
        .unwrap();
        assert_eq!(response.status().unwrap(), reqwest::StatusCode::OK);
    }
    server.join().unwrap();
    assert_eq!(provider.silent_calls.load(Ordering::SeqCst), 1);
}

#[test]
fn concurrent_access_requests_share_one_silent_acquisition() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    *provider.silent_delay.lock().unwrap() = Duration::from_millis(25);
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(provider.clone(), settings);
    let start = Arc::new(Barrier::new(3));

    let workers: Vec<_> = (0..2)
        .map(|_| {
            let manager = Arc::clone(&manager);
            let start = Arc::clone(&start);
            thread::spawn(move || {
                start.wait();
                tauri::async_runtime::block_on(manager.access_token())
                    .unwrap()
                    .is_some()
            })
        })
        .collect();
    start.wait();
    for worker in workers {
        assert!(worker.join().unwrap());
    }
    assert_eq!(provider.silent_calls.load(Ordering::SeqCst), 1);
}

#[test]
fn configuration_change_during_silent_acquisition_rejects_the_stale_grant() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    let gate = SilentGate::new();
    provider.set_silent_gate(gate.clone());
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(provider, settings.clone());
    let worker_manager = Arc::clone(&manager);
    let worker = thread::spawn(move || {
        tauri::async_runtime::block_on(worker_manager.access_token())
            .err()
            .unwrap()
    });

    tauri::async_runtime::block_on(gate.wait_until_entered());
    settings.lock().unwrap().authentication = Some(entra_settings(2));
    gate.release();

    assert_eq!(
        worker.join().unwrap(),
        RequestAuthorizationError::AccountChanged
    );
    assert!(!manager.session_is_open());
}

#[test]
fn expired_silent_grants_fail_closed() {
    let expired = FakeGrant {
        expires_at_unix_seconds: now_unix_seconds(),
        ..FakeGrant::valid()
    };
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    provider.set_silent_grant(expired);
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(provider, settings);

    assert_eq!(
        tauri::async_runtime::block_on(manager.access_token())
            .err()
            .unwrap(),
        RequestAuthorizationError::InvalidToken
    );
    assert!(tauri::async_runtime::block_on(manager.state.lock())
        .cached_token
        .is_none());
}

#[test]
fn slow_silent_grant_is_rechecked_against_the_refresh_margin_after_provider_return() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    provider.set_silent_grant(FakeGrant {
        access_token: "slow-token".into(),
        expires_at_unix_seconds: 1_201,
        account_id: "test-account.tenant".into(),
    });
    let gate = SilentGate::new();
    provider.set_silent_gate(gate.clone());
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let now = Arc::new(AtomicU64::new(1_000));
    let clock_now = Arc::clone(&now);
    let manager = manager_with_clock(
        provider,
        settings,
        Arc::new(move || clock_now.load(Ordering::SeqCst)),
    );
    let worker = thread::spawn(move || {
        tauri::async_runtime::block_on(manager.access_token())
            .err()
            .unwrap()
    });

    tauri::async_runtime::block_on(gate.wait_until_entered());
    now.store(1_082, Ordering::SeqCst);
    gate.release();

    assert_eq!(
        worker.join().unwrap(),
        RequestAuthorizationError::InvalidToken
    );
}

#[test]
fn near_expiry_interactive_grant_is_rejected_before_a_session_reopens() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    provider.set_interactive_grant(FakeGrant {
        access_token: "interactive-token".into(),
        expires_at_unix_seconds: 1_120,
        account_id: "test-account.tenant".into(),
    });
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager_with_clock(provider, settings, Arc::new(|| 1_000));

    assert_eq!(
        tauri::async_runtime::block_on(manager.sign_in(None)).unwrap_err(),
        "Microsoft Entra returned an invalid sign-in response."
    );
    assert!(tauri::async_runtime::block_on(manager.state.lock())
        .cached_token
        .is_none());
    assert!(!manager.session.is_open());
}

#[test]
fn silent_provider_outcomes_fail_before_server_dispatch() {
    let outcomes = [
        (
            NativeAccessTokenProviderError::INTERACTION_REQUIRED,
            RequestAuthorizationError::Unavailable,
        ),
        (
            NativeAccessTokenProviderError::CANCELLED,
            RequestAuthorizationError::Unavailable,
        ),
        (
            NativeAccessTokenProviderError::CONFIGURATION,
            RequestAuthorizationError::Unavailable,
        ),
        (
            NativeAccessTokenProviderError::POLICY_DENIED,
            RequestAuthorizationError::Unavailable,
        ),
        (
            NativeAccessTokenProviderError::NETWORK,
            RequestAuthorizationError::Unavailable,
        ),
        (
            NativeAccessTokenProviderError::INVALID_SESSION,
            RequestAuthorizationError::AccountChanged,
        ),
        (
            NativeAccessTokenProviderError::UNAVAILABLE,
            RequestAuthorizationError::Unavailable,
        ),
    ];

    for (provider_error, expected) in outcomes {
        let provider = Arc::new(FakeNativeAccessTokenProvider::with_silent_error(
            provider_error,
        ));
        let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
        let manager = manager(provider, settings);
        assert_eq!(
            tauri::async_runtime::block_on(manager.access_token())
                .err()
                .unwrap(),
            expected
        );
        if provider_error == NativeAccessTokenProviderError::INVALID_SESSION {
            assert!(!manager.session_is_open());
        }
    }
}

#[test]
fn sign_out_during_authorization_cancels_the_grant_and_prevents_network_dispatch() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    let gate = SilentGate::new();
    provider.set_silent_gate(gate.clone());
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(provider.clone(), settings);
    let authenticated = dispatcher(&manager);
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let worker = thread::spawn({
        let authenticated = authenticated.clone();
        move || {
            tauri::async_runtime::block_on(
                authenticated.send(authenticated.get(format!("http://{address}/protected"))),
            )
            .unwrap_err()
        }
    });

    tauri::async_runtime::block_on(gate.wait_until_entered());
    tauri::async_runtime::block_on(manager.sign_out()).unwrap();

    assert!(matches!(
        worker.join().unwrap(),
        AuthenticatedDispatchError::Authorization(RequestAuthorizationError::AccountChanged)
    ));
    assert_eq!(provider.sign_out_calls.load(Ordering::SeqCst), 1);
    listener.set_nonblocking(true).unwrap();
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
    assert!(matches!(
        tauri::async_runtime::block_on(
            authenticated.send(authenticated.get(format!("http://{address}/after-sign-out")))
        )
        .unwrap_err(),
        AuthenticatedDispatchError::Authorization(RequestAuthorizationError::Unavailable)
    ));
}

#[test]
fn sign_out_cancels_and_drains_an_in_flight_server_send_before_returning() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(provider.clone(), settings);
    assert!(tauri::async_runtime::block_on(manager.access_token())
        .unwrap()
        .is_some());
    let authenticated = dispatcher(&manager);
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let (request_started_tx, request_started_rx) = std::sync::mpsc::channel();
    let (release_server_tx, release_server_rx) = std::sync::mpsc::channel();
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut request = [0_u8; 2048];
        let read = stream.read(&mut request).unwrap();
        assert!(String::from_utf8_lossy(&request[..read])
            .to_ascii_lowercase()
            .contains("authorization: bearer test-token\r\n"));
        request_started_tx.send(()).unwrap();
        release_server_rx
            .recv_timeout(Duration::from_secs(2))
            .unwrap();
        let _ =
            stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
    });
    let worker = thread::spawn({
        let authenticated = authenticated.clone();
        move || {
            tauri::async_runtime::block_on(
                authenticated.send(authenticated.get(format!("http://{address}/protected"))),
            )
            .unwrap_err()
        }
    });

    request_started_rx
        .recv_timeout(Duration::from_secs(2))
        .unwrap();
    tauri::async_runtime::block_on(manager.sign_out()).unwrap();

    assert!(matches!(
        worker.join().unwrap(),
        AuthenticatedDispatchError::Authorization(RequestAuthorizationError::AccountChanged)
    ));
    assert_eq!(provider.sign_out_calls.load(Ordering::SeqCst), 1);
    release_server_tx.send(()).unwrap();
    server.join().unwrap();
}

#[test]
fn settings_transition_drains_the_old_authenticated_session_before_publication() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    let authentication = entra_settings(1);
    let settings = Arc::new(StandardMutex::new(server_settings(Some(
        authentication.clone(),
    ))));
    let manager = manager(provider, settings);
    assert!(tauri::async_runtime::block_on(manager.access_token())
        .unwrap()
        .is_some());
    let authenticated = dispatcher(&manager);
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let (request_started_tx, request_started_rx) = std::sync::mpsc::channel();
    let (release_server_tx, release_server_rx) = std::sync::mpsc::channel();
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut request = [0_u8; 2048];
        let read = stream.read(&mut request).unwrap();
        assert!(String::from_utf8_lossy(&request[..read])
            .to_ascii_lowercase()
            .contains("authorization: bearer test-token\r\n"));
        request_started_tx.send(()).unwrap();
        release_server_rx
            .recv_timeout(Duration::from_secs(2))
            .unwrap();
    });
    let worker = thread::spawn(move || {
        tauri::async_runtime::block_on(
            authenticated.send(authenticated.get(format!("http://{address}/protected"))),
        )
        .unwrap_err()
    });

    request_started_rx
        .recv_timeout(Duration::from_secs(2))
        .unwrap();
    tauri::async_runtime::block_on(manager.transition_configuration(Some(&authentication), || {
        assert!(matches!(
            worker.join().unwrap(),
            AuthenticatedDispatchError::Authorization(RequestAuthorizationError::AccountChanged)
        ));
        ((), Some(authentication.clone()))
    }));

    assert!(manager.session_is_open());
    release_server_tx.send(()).unwrap();
    server.join().unwrap();
}

#[test]
fn silent_account_switch_closes_an_active_live_session_without_dispatching_account_b() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    provider.set_interactive_grant(FakeGrant {
        access_token: "account-a-token".into(),
        expires_at_unix_seconds: 1_400,
        account_id: "account-a.tenant".into(),
    });
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let now = Arc::new(AtomicU64::new(1_000));
    let clock_now = Arc::clone(&now);
    let manager = manager_with_clock(
        Arc::clone(&provider),
        settings,
        Arc::new(move || clock_now.load(Ordering::SeqCst)),
    );
    tauri::async_runtime::block_on(manager.sign_in(None)).unwrap();

    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let server_listener = listener.try_clone().unwrap();
    let server = thread::spawn(move || {
        let (stream, _) = server_listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        stream
            .set_write_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        let mut websocket = accept_hdr(stream, |request: &Request, mut response: Response| {
            assert_eq!(
                request.headers().get(AUTHORIZATION).unwrap(),
                "Bearer account-a-token"
            );
            response.headers_mut().insert(
                SEC_WEBSOCKET_PROTOCOL,
                HeaderValue::from_static("yap.live.v1"),
            );
            Ok(response)
        })
        .unwrap();
        loop {
            match websocket.read() {
                Ok(ServerMessage::Close(_)) | Err(_) => break,
                Ok(_) => {}
            }
        }
    });

    let authenticated = dispatcher(&manager);
    let mut connection = tauri::async_runtime::block_on(
        authenticated.connect_approved_live(&format!("http://{address}")),
    )
    .unwrap();

    provider.set_silent_grant(FakeGrant {
        access_token: "account-b-token".into(),
        expires_at_unix_seconds: 2_000,
        account_id: "account-b.tenant".into(),
    });
    now.store(1_281, Ordering::SeqCst);
    assert_eq!(
        tauri::async_runtime::block_on(manager.access_token())
            .err()
            .unwrap(),
        RequestAuthorizationError::AccountChanged
    );
    assert!(!manager.session_is_open());
    assert_eq!(
        tauri::async_runtime::block_on(connection.receive()).unwrap_err(),
        crate::server_connector::AuthenticatedLiveError::AccountChanged
    );

    listener.set_nonblocking(true).unwrap();
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
    server.join().unwrap();
}

#[test]
fn concurrent_sign_in_and_refresh_never_overlap_native_provider_calls() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    let gate = SilentGate::new();
    provider.set_silent_gate(gate.clone());
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(provider.clone(), settings);
    let authenticated = dispatcher(&manager);
    let refresh = thread::spawn(move || {
        tauri::async_runtime::block_on(
            authenticated.send(authenticated.get("http://127.0.0.1:9/protected")),
        )
        .unwrap_err()
    });

    tauri::async_runtime::block_on(gate.wait_until_entered());
    let sign_in = thread::spawn({
        let manager = Arc::clone(&manager);
        move || tauri::async_runtime::block_on(manager.sign_in(Some(42)))
    });

    assert!(matches!(
        refresh.join().unwrap(),
        AuthenticatedDispatchError::Authorization(RequestAuthorizationError::AccountChanged)
    ));
    sign_in.join().unwrap().unwrap();
    assert_eq!(provider.silent_calls.load(Ordering::SeqCst), 1);
    assert_eq!(provider.interactive_calls.load(Ordering::SeqCst), 1);
    assert_eq!(provider.maximum_active_calls.load(Ordering::SeqCst), 1);
    assert!(manager.session.is_open());
}

#[test]
fn production_discovery_has_no_unapproved_provider_and_fails_closed() {
    assert!(NativeAccessTokenManager::discover().provider.is_none());
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = Arc::new(NativeAccessTokenManager {
        provider: None,
        settings_loader: Arc::new(move || Ok(settings.lock().unwrap().clone())),
        state: Mutex::new(AccessTokenState::default()),
        lifecycle: Mutex::new(()),
        session: AuthenticatedSession::new(),
        clock: Arc::new(now_unix_seconds),
    });

    assert_eq!(
        tauri::async_runtime::block_on(manager.access_token())
            .err()
            .unwrap(),
        RequestAuthorizationError::Unavailable
    );
}

#[test]
fn absent_configuration_preserves_unauthenticated_local_operation() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    let settings = Arc::new(StandardMutex::new(server_settings(None)));
    let manager = manager(provider.clone(), settings);

    assert!(tauri::async_runtime::block_on(manager.access_token())
        .unwrap()
        .is_none());
    assert_eq!(provider.silent_calls.load(Ordering::SeqCst), 0);
}

#[test]
fn interactive_sign_in_status_and_sign_out_share_the_native_owner() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(provider.clone(), settings);

    tauri::async_runtime::block_on(manager.sign_in(Some(123))).unwrap();
    let status = tauri::async_runtime::block_on(manager.status()).unwrap();
    assert!(status.configured);
    assert!(status.signed_in);
    tauri::async_runtime::block_on(manager.sign_out()).unwrap();
    assert_eq!(provider.interactive_calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        provider.last_parent_window_handle.load(Ordering::SeqCst),
        123
    );
    assert_eq!(provider.status_calls.load(Ordering::SeqCst), 1);
    assert_eq!(provider.sign_out_calls.load(Ordering::SeqCst), 1);
}

#[test]
fn interactive_cancellation_is_distinct_and_does_not_cache_a_token() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    provider.set_interactive_error(NativeAccessTokenProviderError::CANCELLED);
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(provider, settings);

    assert_eq!(
        tauri::async_runtime::block_on(manager.sign_in(None)).unwrap_err(),
        "Sign-in was cancelled."
    );
    assert!(tauri::async_runtime::block_on(manager.state.lock())
        .cached_token
        .is_none());
}

#[test]
fn status_reports_signed_out_and_clears_cached_access() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(provider.clone(), settings);
    assert!(tauri::async_runtime::block_on(manager.access_token())
        .unwrap()
        .is_some());

    provider.set_status(FakeSession::SignedOut);
    let status = tauri::async_runtime::block_on(manager.status()).unwrap();

    assert!(status.configured);
    assert!(!status.signed_in);
    assert!(tauri::async_runtime::block_on(manager.state.lock())
        .cached_token
        .is_none());
}

#[test]
fn status_failure_closes_the_identity_session_and_clears_its_binding() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(provider.clone(), settings);
    assert!(tauri::async_runtime::block_on(manager.access_token())
        .unwrap()
        .is_some());

    provider.set_status_error(NativeAccessTokenProviderError::NETWORK);
    assert_eq!(
        tauri::async_runtime::block_on(manager.status()).unwrap_err(),
        "Identity provider network request failed."
    );
    assert!(!manager.session_is_open());
    let state = tauri::async_runtime::block_on(manager.state.lock());
    assert!(state.cached_token.is_none());
    assert!(state.active_binding.is_none());
}

#[test]
fn status_account_change_invalidates_stale_cached_access() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(provider.clone(), settings);
    assert!(tauri::async_runtime::block_on(manager.access_token())
        .unwrap()
        .is_some());

    provider.set_status(FakeSession::SignedIn("different-account.tenant".into()));
    assert_eq!(
        tauri::async_runtime::block_on(manager.status()).unwrap_err(),
        "Microsoft Entra account changed during the active session."
    );
    assert!(tauri::async_runtime::block_on(manager.state.lock())
        .cached_token
        .is_none());
    assert!(tauri::async_runtime::block_on(manager.state.lock())
        .active_binding
        .is_none());
    assert!(!manager.session_is_open());
}

#[test]
fn configuration_change_invalidates_stale_access_and_signs_out_old_session() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    let previous = entra_settings(1);
    let settings = Arc::new(StandardMutex::new(server_settings(Some(previous.clone()))));
    let manager = manager(provider.clone(), settings.clone());
    assert!(tauri::async_runtime::block_on(manager.access_token())
        .unwrap()
        .is_some());

    settings.lock().unwrap().authentication = Some(entra_settings(2));
    assert_eq!(
        tauri::async_runtime::block_on(manager.access_token())
            .err()
            .unwrap(),
        RequestAuthorizationError::AccountChanged
    );
    assert!(!manager.session_is_open());
    tauri::async_runtime::block_on(manager.configuration_changed(Some(&previous)));
    assert!(manager.session_is_open());
    assert!(tauri::async_runtime::block_on(manager.access_token())
        .unwrap()
        .is_some());

    assert!(tauri::async_runtime::block_on(manager.state.lock())
        .cached_token
        .is_some());
    assert_eq!(provider.silent_calls.load(Ordering::SeqCst), 3);
    assert_eq!(provider.sign_out_calls.load(Ordering::SeqCst), 1);
}

#[test]
fn sign_out_clears_cached_access_even_when_provider_cleanup_fails() {
    let provider = Arc::new(FakeNativeAccessTokenProvider::valid());
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(provider.clone(), settings);
    assert!(tauri::async_runtime::block_on(manager.access_token())
        .unwrap()
        .is_some());
    provider.set_sign_out_error(NativeAccessTokenProviderError::NETWORK);

    assert_eq!(
        tauri::async_runtime::block_on(manager.sign_out()).unwrap_err(),
        "Identity provider network request failed."
    );
    assert!(tauri::async_runtime::block_on(manager.state.lock())
        .cached_token
        .is_none());
}

#[test]
fn account_identity_rejects_whitespace_before_binding() {
    assert_eq!(
        account_binding("unexpected account").unwrap_err(),
        RequestAuthorizationError::InvalidToken
    );
}

#[test]
fn authentication_binding_changes_with_client_or_api_scope() {
    let baseline = entra_settings(1);
    let baseline_binding = authentication_binding(&baseline).unwrap();
    assert_eq!(baseline_binding, authentication_binding(&baseline).unwrap());

    let mut changed_client = baseline.clone();
    changed_client.client_id = "99999999-2222-2222-2222-222222222222".into();
    assert_ne!(
        baseline_binding,
        authentication_binding(&changed_client).unwrap()
    );

    let mut changed_scope = baseline;
    changed_scope.api_scope = "api://99999999-3333-3333-3333-333333333333/access_as_user".into();
    assert_ne!(
        baseline_binding,
        authentication_binding(&changed_scope).unwrap()
    );
}
