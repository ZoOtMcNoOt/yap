use std::{
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    sync::{atomic::AtomicU64, mpsc as std_mpsc, Arc, Mutex as StandardMutex},
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
    Message as ServerMessage, WebSocket as ServerWebSocket,
};

use super::*;
use crate::server_connector::authorization::{
    AccessToken, AccessTokenFuture, AccountBinding, AuthenticatedSession, AuthenticationBinding,
    AuthorizedAccess, ServerAccessTokenSource,
};

const SECRET_TOKEN: &str = "native-live-secret";
const TEST_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Debug)]
struct HandshakeObservation {
    target: String,
    authorization: Option<String>,
    protocols: Option<String>,
}

struct FixedTokenSource;

impl ServerAccessTokenSource for FixedTokenSource {
    fn access(&self) -> AccessTokenFuture<'_> {
        Box::pin(async { Ok(Some(test_access(SECRET_TOKEN))) })
    }
}

struct UnavailableTokenSource;

impl ServerAccessTokenSource for UnavailableTokenSource {
    fn access(&self) -> AccessTokenFuture<'_> {
        Box::pin(async { Err(RequestAuthorizationError::Unavailable) })
    }
}

struct PendingTokenSource {
    entered: StandardMutex<Option<std_mpsc::Sender<()>>>,
}

impl PendingTokenSource {
    fn new() -> (Arc<Self>, std_mpsc::Receiver<()>) {
        let (entered, observed) = std_mpsc::channel();
        (
            Arc::new(Self {
                entered: StandardMutex::new(Some(entered)),
            }),
            observed,
        )
    }
}

impl ServerAccessTokenSource for PendingTokenSource {
    fn access(&self) -> AccessTokenFuture<'_> {
        Box::pin(async move {
            if let Some(entered) = self.entered.lock().unwrap().take() {
                let _ = entered.send(());
            }
            std::future::pending().await
        })
    }
}

fn test_access(token: &str) -> AuthorizedAccess {
    AuthorizedAccess::new(
        AccessToken::new(token.to_owned()).unwrap(),
        AccountBinding::new("a".repeat(64)).unwrap(),
        AuthenticationBinding::new("b".repeat(64)).unwrap(),
    )
}

fn dispatcher(
    source: Arc<dyn ServerAccessTokenSource>,
    session: Arc<AuthenticatedSession>,
) -> AuthenticatedRequestDispatcher {
    AuthenticatedRequestDispatcher::from_source(reqwest::Client::new(), source, session)
}

fn spawn_websocket_server(
    handler: impl FnOnce(ServerWebSocket<TcpStream>) + Send + 'static,
) -> (
    String,
    std_mpsc::Receiver<HandshakeObservation>,
    thread::JoinHandle<()>,
) {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let (observed, observations) = std_mpsc::channel();
    let server = thread::spawn(move || {
        let (stream, _) = listener.accept().unwrap();
        stream.set_read_timeout(Some(TEST_TIMEOUT)).unwrap();
        stream.set_write_timeout(Some(TEST_TIMEOUT)).unwrap();
        let websocket = accept_hdr(stream, move |request: &Request, mut response: Response| {
            let authorization = request
                .headers()
                .get(AUTHORIZATION)
                .and_then(|value| value.to_str().ok())
                .map(str::to_owned);
            let protocols = request
                .headers()
                .get(SEC_WEBSOCKET_PROTOCOL)
                .and_then(|value| value.to_str().ok())
                .map(str::to_owned);
            observed
                .send(HandshakeObservation {
                    target: request.uri().to_string(),
                    authorization,
                    protocols,
                })
                .unwrap();
            response.headers_mut().insert(
                SEC_WEBSOCKET_PROTOCOL,
                HeaderValue::from_static(LIVE_SUBPROTOCOL),
            );
            Ok(response)
        })
        .unwrap();
        handler(websocket);
    });
    (format!("http://{address}"), observations, server)
}

fn spawn_raw_http_server(
    response: &'static [u8],
) -> (String, std_mpsc::Receiver<String>, thread::JoinHandle<()>) {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let (observed, observations) = std_mpsc::channel();
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream.set_read_timeout(Some(TEST_TIMEOUT)).unwrap();
        let request = read_headers(&mut stream);
        observed.send(request).unwrap();
        stream.write_all(response).unwrap();
    });
    (format!("http://{address}"), observations, server)
}

fn spawn_stalled_handshake() -> (String, std_mpsc::Receiver<()>, thread::JoinHandle<()>) {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let (started, observed) = std_mpsc::channel();
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream.set_read_timeout(Some(TEST_TIMEOUT)).unwrap();
        let request = read_headers(&mut stream);
        assert!(request
            .to_ascii_lowercase()
            .contains("authorization: bearer native-live-secret\r\n"));
        started.send(()).unwrap();
        let mut byte = [0_u8; 1];
        while stream.read(&mut byte).is_ok_and(|read| read != 0) {}
    });
    (format!("http://{address}"), observed, server)
}

fn read_headers(stream: &mut TcpStream) -> String {
    let mut bytes = Vec::new();
    let mut chunk = [0_u8; 512];
    while !bytes.ends_with(b"\r\n\r\n") {
        let read = stream.read(&mut chunk).unwrap();
        assert_ne!(read, 0, "connection closed before the HTTP headers");
        bytes.extend_from_slice(&chunk[..read]);
        assert!(
            bytes.len() <= 32 * 1024,
            "test handshake headers are bounded"
        );
    }
    String::from_utf8(bytes).unwrap()
}

fn echo_until_closed(mut websocket: ServerWebSocket<TcpStream>) {
    loop {
        match websocket.read() {
            Ok(ServerMessage::Text(text)) => {
                if websocket.send(ServerMessage::Text(text)).is_err() {
                    break;
                }
            }
            Ok(ServerMessage::Binary(bytes)) => {
                if websocket.send(ServerMessage::Binary(bytes)).is_err() {
                    break;
                }
            }
            Ok(ServerMessage::Close(_)) | Err(_) => break,
            Ok(_) => {}
        }
    }
}

#[test]
fn explicit_live_origin_is_fixed_scheme_bounded_and_does_not_infer_a_private_port() {
    assert_eq!(
        resolve_authenticated_live_endpoint("https://approved.example/v1")
            .unwrap()
            .as_str(),
        "wss://approved.example/v1/live"
    );
    assert_eq!(
        resolve_authenticated_live_endpoint("http://127.0.0.1:18766")
            .unwrap()
            .as_str(),
        "ws://127.0.0.1:18766/v1/live"
    );
    assert_eq!(
        resolve_authenticated_live_endpoint("http://127.0.0.1:18765")
            .unwrap()
            .as_str(),
        "ws://127.0.0.1:18765/v1/live"
    );
    assert_eq!(
        resolve_authenticated_live_endpoint("http://192.168.50.2:18766").unwrap_err(),
        AuthenticatedLiveError::InvalidOrigin
    );
    assert_eq!(
        resolve_authenticated_live_endpoint("http://public.example").unwrap_err(),
        AuthenticatedLiveError::InvalidOrigin
    );
    assert_eq!(
        resolve_authenticated_live_endpoint("https://approved.example?token=secret").unwrap_err(),
        AuthenticatedLiveError::InvalidOrigin
    );
}

#[test]
fn native_handshake_injects_only_the_header_and_negotiates_exact_protocol() {
    let (origin, observations, server) = spawn_websocket_server(echo_until_closed);
    let session = AuthenticatedSession::new();
    let connector_generation = Arc::new(AtomicU64::new(4));
    let authenticated = dispatcher(Arc::new(FixedTokenSource), session)
        .with_connector_generation(connector_generation)
        .bind_current_transport(4, &origin)
        .unwrap();
    let mut connection =
        tauri::async_runtime::block_on(authenticated.connect_approved_live(&origin)).unwrap();
    let observation = observations.recv_timeout(TEST_TIMEOUT).unwrap();

    assert_eq!(observation.target, LIVE_PATH);
    assert_eq!(
        observation.authorization.as_deref(),
        Some("Bearer native-live-secret")
    );
    assert_eq!(observation.protocols.as_deref(), Some(LIVE_SUBPROTOCOL));
    assert!(!observation.target.contains(SECRET_TOKEN));

    tauri::async_runtime::block_on(connection.send(AuthenticatedLiveMessage::Text(
        r#"{"type":"session.start"}"#.to_owned(),
    )))
    .unwrap();
    assert_eq!(
        tauri::async_runtime::block_on(connection.receive()).unwrap(),
        Some(AuthenticatedLiveMessage::Text(
            r#"{"type":"session.start"}"#.to_owned()
        ))
    );
    tauri::async_runtime::block_on(connection.close()).unwrap();
    server.join().unwrap();
}

#[test]
fn missing_provider_fails_before_network_dispatch() {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    let authenticated = dispatcher(
        Arc::new(UnavailableTokenSource),
        AuthenticatedSession::new(),
    );

    let error =
        tauri::async_runtime::block_on(authenticated.connect_approved_live(&origin)).unwrap_err();

    assert_eq!(error, AuthenticatedLiveError::AuthorizationUnavailable);
    listener.set_nonblocking(true).unwrap();
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
}

#[test]
fn rejected_handshake_is_typed_and_does_not_disclose_the_token() {
    let (origin, observations, server) = spawn_raw_http_server(
        b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
    );
    let authenticated = dispatcher(Arc::new(FixedTokenSource), AuthenticatedSession::new());

    let error =
        tauri::async_runtime::block_on(authenticated.connect_approved_live(&origin)).unwrap_err();
    let request = observations.recv_timeout(TEST_TIMEOUT).unwrap();

    assert_eq!(error, AuthenticatedLiveError::SignInRequired);
    assert!(request
        .to_ascii_lowercase()
        .contains("authorization: bearer native-live-secret\r\n"));
    assert!(!format!("{error:?} {error}").contains(SECRET_TOKEN));
    assert!(!request.lines().next().unwrap().contains(SECRET_TOKEN));
    server.join().unwrap();
}

#[test]
fn missing_required_subprotocol_fails_closed() {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    let server = thread::spawn(move || {
        let (stream, _) = listener.accept().unwrap();
        stream.set_read_timeout(Some(TEST_TIMEOUT)).unwrap();
        let _ = accept_hdr(stream, |_request: &Request, response: Response| {
            Ok(response)
        });
    });
    let authenticated = dispatcher(Arc::new(FixedTokenSource), AuthenticatedSession::new());

    assert_eq!(
        tauri::async_runtime::block_on(authenticated.connect_approved_live(&origin)).unwrap_err(),
        AuthenticatedLiveError::ProtocolRejected
    );
    server.join().unwrap();
}

#[test]
fn sign_out_before_connect_and_during_token_acquisition_never_dispatches() {
    let session = AuthenticatedSession::new();
    session.invalidate_current();
    let authenticated = dispatcher(Arc::new(FixedTokenSource), session);
    assert_eq!(
        tauri::async_runtime::block_on(authenticated.connect_approved_live("http://127.0.0.1:9"))
            .unwrap_err(),
        AuthenticatedLiveError::AuthorizationUnavailable
    );

    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    let session = AuthenticatedSession::new();
    let (source, entered) = PendingTokenSource::new();
    let authenticated = dispatcher(source, Arc::clone(&session));
    let worker = thread::spawn(move || {
        tauri::async_runtime::block_on(authenticated.connect_approved_live(&origin)).unwrap_err()
    });
    entered.recv_timeout(TEST_TIMEOUT).unwrap();
    tauri::async_runtime::block_on(session.invalidate_and_wait());

    assert_eq!(
        worker.join().unwrap(),
        AuthenticatedLiveError::AccountChanged
    );
    listener.set_nonblocking(true).unwrap();
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
}

#[test]
fn sign_out_during_handshake_cancels_and_drains() {
    let (origin, handshake_started, server) = spawn_stalled_handshake();
    let session = AuthenticatedSession::new();
    let authenticated = dispatcher(Arc::new(FixedTokenSource), Arc::clone(&session));
    let worker = thread::spawn(move || {
        tauri::async_runtime::block_on(authenticated.connect_approved_live(&origin)).unwrap_err()
    });
    handshake_started.recv_timeout(TEST_TIMEOUT).unwrap();

    tauri::async_runtime::block_on(async {
        tokio::time::timeout(TEST_TIMEOUT, session.invalidate_and_wait())
            .await
            .unwrap();
    });

    assert_eq!(
        worker.join().unwrap(),
        AuthenticatedLiveError::AccountChanged
    );
    server.join().unwrap();
}

#[test]
fn sign_out_of_an_idle_connection_drains_without_dropping_the_handle() {
    let (origin, _observations, server) = spawn_websocket_server(echo_until_closed);
    let session = AuthenticatedSession::new();
    let authenticated = dispatcher(Arc::new(FixedTokenSource), Arc::clone(&session));
    let mut connection =
        tauri::async_runtime::block_on(authenticated.connect_approved_live(&origin)).unwrap();

    tauri::async_runtime::block_on(async {
        tokio::time::timeout(TEST_TIMEOUT, session.invalidate_and_wait())
            .await
            .unwrap();
    });

    assert_eq!(
        tauri::async_runtime::block_on(connection.receive()).unwrap_err(),
        AuthenticatedLiveError::AccountChanged
    );
    server.join().unwrap();
}

#[test]
fn a_replaced_session_generation_rejects_the_stale_connect() {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    let session = AuthenticatedSession::new();
    let (source, entered) = PendingTokenSource::new();
    let authenticated = dispatcher(source, Arc::clone(&session));
    let worker = thread::spawn(move || {
        tauri::async_runtime::block_on(authenticated.connect_approved_live(&origin)).unwrap_err()
    });
    entered.recv_timeout(TEST_TIMEOUT).unwrap();

    session.invalidate_current();
    session.open_new_generation();

    assert_eq!(
        worker.join().unwrap(),
        AuthenticatedLiveError::AccountChanged
    );
    listener.set_nonblocking(true).unwrap();
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
}

#[test]
fn outbound_and_inbound_protocol_bounds_are_enforced() {
    let (origin, _observations, server) = spawn_websocket_server(echo_until_closed);
    let authenticated = dispatcher(Arc::new(FixedTokenSource), AuthenticatedSession::new());
    let connection =
        tauri::async_runtime::block_on(authenticated.connect_approved_live(&origin)).unwrap();

    assert_eq!(
        tauri::async_runtime::block_on(connection.send(AuthenticatedLiveMessage::Text(
            "x".repeat(MAX_TEXT_MESSAGE_BYTES + 1)
        )))
        .unwrap_err(),
        AuthenticatedLiveError::MessageTooLarge
    );
    assert_eq!(
        tauri::async_runtime::block_on(connection.send(AuthenticatedLiveMessage::Binary(vec![
                0;
                MAX_BINARY_MESSAGE_BYTES + 1
            ])))
        .unwrap_err(),
        AuthenticatedLiveError::MessageTooLarge
    );
    tauri::async_runtime::block_on(connection.close()).unwrap();
    server.join().unwrap();

    let (origin, _observations, server) = spawn_websocket_server(|mut websocket| {
        let _ = websocket.send(ServerMessage::Text(
            "x".repeat(MAX_TEXT_MESSAGE_BYTES + 1).into(),
        ));
        let _ = websocket.read();
    });
    let authenticated = dispatcher(Arc::new(FixedTokenSource), AuthenticatedSession::new());
    let mut connection =
        tauri::async_runtime::block_on(authenticated.connect_approved_live(&origin)).unwrap();

    assert_eq!(
        tauri::async_runtime::block_on(connection.receive()).unwrap_err(),
        AuthenticatedLiveError::MessageTooLarge
    );
    drop(connection);
    server.join().unwrap();
}

#[test]
fn inbound_queue_overflow_fails_the_connection_with_backpressure() {
    let (origin, _observations, server) = spawn_websocket_server(|mut websocket| {
        for sequence in 0..=MAX_PENDING_EVENTS {
            if websocket
                .send(ServerMessage::Text(format!("{sequence}").into()))
                .is_err()
            {
                break;
            }
        }
        let _ = websocket.read();
    });
    let authenticated = dispatcher(Arc::new(FixedTokenSource), AuthenticatedSession::new());
    let mut connection =
        tauri::async_runtime::block_on(authenticated.connect_approved_live(&origin)).unwrap();

    tauri::async_runtime::block_on(async {
        tokio::time::timeout(TEST_TIMEOUT, connection.terminal.changed())
            .await
            .unwrap()
            .unwrap();
    });
    assert_eq!(
        *connection.terminal.borrow(),
        Some(Err(AuthenticatedLiveError::Backpressure))
    );
    for sequence in 0..MAX_PENDING_EVENTS {
        assert_eq!(
            tauri::async_runtime::block_on(connection.receive()).unwrap(),
            Some(AuthenticatedLiveMessage::Text(sequence.to_string()))
        );
    }
    assert_eq!(
        tauri::async_runtime::block_on(connection.receive()).unwrap_err(),
        AuthenticatedLiveError::Backpressure
    );
    server.join().unwrap();
}

#[test]
fn outbound_queue_overflow_is_immediate_typed_backpressure() {
    let (commands, _pending_commands) = mpsc::channel(1);
    let (queued_acknowledgement, _queued_result) = oneshot::channel();
    assert!(commands
        .try_send(LiveCommand::Send {
            message: AuthenticatedLiveMessage::Text("already queued".to_owned()),
            acknowledgement: queued_acknowledgement,
        })
        .is_ok());
    let (_event_sender, events) = mpsc::channel(1);
    let (_terminal_sender, terminal) = watch::channel(None);
    let connection = AuthenticatedLiveConnection {
        commands,
        events,
        terminal,
    };

    assert_eq!(
        tauri::async_runtime::block_on(
            connection.send(AuthenticatedLiveMessage::Text("next".to_owned()))
        )
        .unwrap_err(),
        AuthenticatedLiveError::Backpressure
    );
}

#[test]
fn python_authenticated_server_accepts_signed_bearer_over_live_websocket_when_provided() {
    let (Ok(origin), Ok(token)) = (
        std::env::var("YAP_TEST_AUTH_SERVER_LIVE_ORIGIN"),
        std::env::var("YAP_TEST_AUTH_SERVER_TOKEN"),
    ) else {
        return;
    };
    let authenticated =
        AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), token.as_str());
    let connection =
        tauri::async_runtime::block_on(authenticated.connect_approved_live(origin.as_str()))
            .expect("the Python live server must admit the native connector bearer");

    tauri::async_runtime::block_on(connection.close())
        .expect("the native connector must close the Python live connection cleanly");
}
