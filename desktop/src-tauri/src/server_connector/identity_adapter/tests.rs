use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc, Mutex as StandardMutex,
};

use zeroize::Zeroizing;

use super::*;
use crate::server_connector::{config::CURRENT_SCHEMA_VERSION, RequestAuthorization};

struct FakeIdentityAdapter {
    calls: AtomicUsize,
    silent_outcome: IdentityOutcome,
    status_account: StandardMutex<String>,
}

impl FakeIdentityAdapter {
    fn new(silent_outcome: IdentityOutcome) -> Self {
        Self {
            calls: AtomicUsize::new(0),
            silent_outcome,
            status_account: StandardMutex::new("test-account.tenant".into()),
        }
    }

    fn set_status_account(&self, account_id: &str) {
        *self.status_account.lock().unwrap() = account_id.into();
    }
}

impl IdentityAdapter for FakeIdentityAdapter {
    fn execute(&self, request: IdentityAdapterRequest) -> IdentityAdapterFuture<'_> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let outcome = match request.operation {
            IdentityOperation::AcquireTokenSilent => self.silent_outcome,
            IdentityOperation::SignInInteractively => IdentityOutcome::SignedIn,
            IdentityOperation::SignOut => IdentityOutcome::SignedOut,
            IdentityOperation::GetStatus => IdentityOutcome::SignedInStatus,
        };
        let account_id = match request.operation {
            IdentityOperation::GetStatus => self.status_account.lock().unwrap().clone(),
            _ => "test-account.tenant".into(),
        };
        Box::pin(async move {
            let token_outcome =
                matches!(outcome, IdentityOutcome::Token | IdentityOutcome::SignedIn);
            let signed_in = token_outcome || matches!(outcome, IdentityOutcome::SignedInStatus);
            Ok(IdentityAdapterResponse {
                schema_version: protocol::IDENTITY_ADAPTER_SCHEMA_VERSION,
                request_id: request.request_id,
                outcome,
                access_token: token_outcome.then(|| Zeroizing::new("test-token".into())),
                expires_at_unix_seconds: token_outcome.then(|| now_unix_seconds() + 3_600),
                account_id: signed_in.then_some(account_id),
                error_code: None,
            })
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
    adapter: Arc<FakeIdentityAdapter>,
    settings: Arc<StandardMutex<ServerSettings>>,
) -> Arc<NativeIdentityManager> {
    Arc::new(NativeIdentityManager {
        adapter: Some(adapter),
        settings_loader: Arc::new(move || Ok(settings.lock().unwrap().clone())),
        state: Mutex::new(IdentityState::default()),
        request_sequence: AtomicU64::new(0),
    })
}

#[test]
fn silent_tokens_are_cached_in_memory_until_the_refresh_margin() {
    let adapter = Arc::new(FakeIdentityAdapter::new(IdentityOutcome::Token));
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(adapter.clone(), settings);
    let authorization = RequestAuthorization::from_source(manager);

    for _ in 0..2 {
        let request = tauri::async_runtime::block_on(
            authorization.authorize(reqwest::Client::new().get("https://example.invalid")),
        )
        .unwrap()
        .build()
        .unwrap();
        assert_eq!(
            request
                .headers()
                .get(reqwest::header::AUTHORIZATION)
                .unwrap(),
            "Bearer test-token"
        );
    }
    assert_eq!(adapter.calls.load(Ordering::SeqCst), 1);
}

#[test]
fn identity_reconfiguration_invalidates_the_in_memory_token() {
    let adapter = Arc::new(FakeIdentityAdapter::new(IdentityOutcome::Token));
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(adapter.clone(), settings.clone());

    assert!(tauri::async_runtime::block_on(manager.access_token())
        .unwrap()
        .is_some());
    settings.lock().unwrap().authentication = Some(entra_settings(2));
    assert!(tauri::async_runtime::block_on(manager.access_token())
        .unwrap()
        .is_some());
    assert_eq!(adapter.calls.load(Ordering::SeqCst), 2);
}

#[test]
fn published_identity_reconfiguration_clears_memory_and_signs_out_the_old_configuration() {
    let adapter = Arc::new(FakeIdentityAdapter::new(IdentityOutcome::Token));
    let previous = entra_settings(1);
    let settings = Arc::new(StandardMutex::new(server_settings(Some(previous.clone()))));
    let manager = manager(adapter.clone(), settings);

    assert!(tauri::async_runtime::block_on(manager.access_token())
        .unwrap()
        .is_some());
    tauri::async_runtime::block_on(manager.configuration_changed(Some(&previous)));

    assert!(tauri::async_runtime::block_on(manager.state.lock())
        .cached_token
        .is_none());
    assert_eq!(adapter.calls.load(Ordering::SeqCst), 2);
}

#[test]
fn absent_configuration_keeps_local_operation_unauthenticated() {
    let adapter = Arc::new(FakeIdentityAdapter::new(IdentityOutcome::Token));
    let settings = Arc::new(StandardMutex::new(server_settings(None)));
    let manager = manager(adapter.clone(), settings);

    assert!(tauri::async_runtime::block_on(manager.access_token())
        .unwrap()
        .is_none());
    assert_eq!(adapter.calls.load(Ordering::SeqCst), 0);
}

#[test]
fn interaction_required_fails_before_a_server_request_is_sent() {
    let adapter = Arc::new(FakeIdentityAdapter::new(
        IdentityOutcome::InteractionRequired,
    ));
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(adapter, settings);

    assert_eq!(
        tauri::async_runtime::block_on(manager.access_token())
            .err()
            .unwrap(),
        RequestAuthorizationError::Unavailable
    );
}

#[test]
fn interactive_sign_in_status_and_sign_out_share_one_native_owner() {
    let adapter = Arc::new(FakeIdentityAdapter::new(IdentityOutcome::Token));
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(adapter.clone(), settings);

    tauri::async_runtime::block_on(manager.sign_in(Some(123))).unwrap();
    let status = tauri::async_runtime::block_on(manager.status()).unwrap();
    assert!(status.configured);
    assert!(status.signed_in);
    tauri::async_runtime::block_on(manager.sign_out()).unwrap();
    assert_eq!(adapter.calls.load(Ordering::SeqCst), 3);
}

#[test]
fn status_clears_a_cached_token_when_the_broker_account_changes() {
    let adapter = Arc::new(FakeIdentityAdapter::new(IdentityOutcome::Token));
    let settings = Arc::new(StandardMutex::new(server_settings(Some(entra_settings(1)))));
    let manager = manager(adapter.clone(), settings);

    assert!(tauri::async_runtime::block_on(manager.access_token())
        .unwrap()
        .is_some());
    adapter.set_status_account("different-account.tenant");
    let status = tauri::async_runtime::block_on(manager.status()).unwrap();

    assert!(status.signed_in);
    assert!(tauri::async_runtime::block_on(manager.state.lock())
        .cached_token
        .is_none());
}

#[test]
fn protocol_rejects_whitespace_in_account_identity() {
    let settings = entra_settings(1);
    let request = IdentityAdapterRequest::new(
        "identity-test".into(),
        IdentityOperation::AcquireTokenSilent,
        &settings,
        None,
    );
    let response = IdentityAdapterResponse {
        schema_version: protocol::IDENTITY_ADAPTER_SCHEMA_VERSION,
        request_id: request.request_id.clone(),
        outcome: IdentityOutcome::Token,
        access_token: Some(Zeroizing::new("test-token".into())),
        expires_at_unix_seconds: Some(now_unix_seconds() + 3_600),
        account_id: Some("unexpected account".into()),
        error_code: None,
    };

    assert_eq!(
        response.validate_for(&request),
        Err(IdentityAdapterProtocolError::InvalidResponse)
    );
}
