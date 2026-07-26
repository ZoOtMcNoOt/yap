use std::{fmt, time::Duration};

use futures_util::{SinkExt, StreamExt};
use reqwest::{Client, StatusCode, Url};
use reqwest_websocket::{HandshakeError, Message, Upgrade, WebSocket};
use tokio::sync::{mpsc, oneshot, watch};

use super::{AuthenticatedRequestDispatcher, RequestAuthorizationError, SessionLease};

const LIVE_PATH: &str = "/v1/live";
const LIVE_SUBPROTOCOL: &str = "yap.live.v1";
const LIVE_CONNECT_TIMEOUT: Duration = Duration::from_secs(5);
const LIVE_SEND_TIMEOUT: Duration = Duration::from_secs(2);
const LIVE_CLOSE_TIMEOUT: Duration = Duration::from_secs(2);
const LIVE_CONNECT_TIMEOUT_SECONDS: u64 = 2;
const MAX_TEXT_MESSAGE_BYTES: usize = 64 * 1024;
const MAX_BINARY_MESSAGE_BYTES: usize = 256 * 1024;
const MAX_PENDING_COMMANDS: usize = 8;
const MAX_PENDING_EVENTS: usize = 8;
const LIVE_READ_BUFFER_BYTES: usize = 64 * 1024;
const LIVE_WRITE_BUFFER_BYTES: usize = 64 * 1024;
const LIVE_MAX_WRITE_BUFFER_BYTES: usize = 512 * 1024;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AuthenticatedLiveMessage {
    Text(String),
    Binary(Vec<u8>),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AuthenticatedLiveError {
    InvalidOrigin,
    OriginNotApproved,
    ConfigurationUnavailable,
    AuthorizationUnavailable,
    InvalidToken,
    AccountChanged,
    SignInRequired,
    AccessDenied,
    HandshakeRejected,
    ProtocolRejected,
    Timeout,
    Transport,
    MessageTooLarge,
    Backpressure,
    Closed,
}

impl fmt::Display for AuthenticatedLiveError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidOrigin => "The live server origin is invalid.",
            Self::OriginNotApproved => "The live server origin is not approved.",
            Self::ConfigurationUnavailable => "The live server configuration is unavailable.",
            Self::AuthorizationUnavailable => {
                "Approved native server authorization is unavailable."
            }
            Self::InvalidToken => "The native server access token is invalid.",
            Self::AccountChanged => "The native server identity session changed.",
            Self::SignInRequired => "Server sign-in is required.",
            Self::AccessDenied => "Server access was denied.",
            Self::HandshakeRejected => "The live server rejected the WebSocket handshake.",
            Self::ProtocolRejected => "The live server did not negotiate the required protocol.",
            Self::Timeout => "The live server connection timed out.",
            Self::Transport => "The live server transport failed.",
            Self::MessageTooLarge => "The live server message exceeds the protocol limit.",
            Self::Backpressure => "The live server connection exceeded its bounded queue.",
            Self::Closed => "The live server connection is closed.",
        })
    }
}

impl std::error::Error for AuthenticatedLiveError {}

#[derive(Debug)]
pub struct AuthenticatedLiveConnection {
    commands: mpsc::Sender<LiveCommand>,
    events: mpsc::Receiver<Result<AuthenticatedLiveMessage, AuthenticatedLiveError>>,
    terminal: watch::Receiver<Option<Result<(), AuthenticatedLiveError>>>,
}

enum LiveCommand {
    Send {
        message: AuthenticatedLiveMessage,
        acknowledgement: oneshot::Sender<Result<(), AuthenticatedLiveError>>,
    },
    Close {
        acknowledgement: oneshot::Sender<Result<(), AuthenticatedLiveError>>,
    },
}

impl AuthenticatedLiveConnection {
    pub async fn send(
        &self,
        message: AuthenticatedLiveMessage,
    ) -> Result<(), AuthenticatedLiveError> {
        validate_outbound(&message)?;
        let (acknowledgement, result) = oneshot::channel();
        self.commands
            .try_send(LiveCommand::Send {
                message,
                acknowledgement,
            })
            .map_err(|error| match error {
                mpsc::error::TrySendError::Full(_) => AuthenticatedLiveError::Backpressure,
                mpsc::error::TrySendError::Closed(_) => self.terminal_error(),
            })?;
        result.await.unwrap_or_else(|_| Err(self.terminal_error()))
    }

    pub async fn receive(
        &mut self,
    ) -> Result<Option<AuthenticatedLiveMessage>, AuthenticatedLiveError> {
        match self.events.recv().await {
            Some(result) => result.map(Some),
            None => match *self.terminal.borrow() {
                Some(Ok(())) | None => Ok(None),
                Some(Err(error)) => Err(error),
            },
        }
    }

    pub async fn close(self) -> Result<(), AuthenticatedLiveError> {
        let (acknowledgement, result) = oneshot::channel();
        if let Err(error) = self
            .commands
            .try_send(LiveCommand::Close { acknowledgement })
        {
            return match error {
                mpsc::error::TrySendError::Full(_) => Err(AuthenticatedLiveError::Backpressure),
                mpsc::error::TrySendError::Closed(_) => match *self.terminal.borrow() {
                    Some(Ok(())) => Ok(()),
                    Some(Err(error)) => Err(error),
                    None => Err(AuthenticatedLiveError::Closed),
                },
            };
        }
        result
            .await
            .unwrap_or_else(|_| match *self.terminal.borrow() {
                Some(result) => result,
                None => Err(AuthenticatedLiveError::Closed),
            })
    }

    fn terminal_error(&self) -> AuthenticatedLiveError {
        match *self.terminal.borrow() {
            Some(Err(error)) => error,
            _ => AuthenticatedLiveError::Closed,
        }
    }
}

impl AuthenticatedRequestDispatcher {
    pub(in crate::server_connector) async fn connect_approved_live(
        &self,
        approved_origin: &str,
    ) -> Result<AuthenticatedLiveConnection, AuthenticatedLiveError> {
        let endpoint = resolve_authenticated_live_endpoint(approved_origin)?;
        self.connect_live_endpoint(endpoint).await
    }

    async fn connect_live_endpoint(
        &self,
        endpoint: Url,
    ) -> Result<AuthenticatedLiveConnection, AuthenticatedLiveError> {
        self.ensure_bound_origin(&endpoint)
            .map_err(map_authorization_error)?;
        let lease = self
            .acquire_dispatch_lease()
            .map_err(map_authorization_error)?;
        let authorized = tokio::select! {
            biased;
            _ = lease.cancelled() => {
                return Err(AuthenticatedLiveError::AccountChanged);
            }
            result = self.authorization.authorize(self.live_client.get(endpoint)) => result,
        };
        let authorized = match authorized {
            Ok(request) => request,
            Err(error) => {
                if error == RequestAuthorizationError::AccountChanged {
                    lease.invalidate_generation();
                }
                return Err(map_authorization_error(error));
            }
        };
        let authorized_url = authorized
            .try_clone()
            .ok_or(AuthenticatedLiveError::AuthorizationUnavailable)?
            .build()
            .map_err(|_| AuthenticatedLiveError::AuthorizationUnavailable)?
            .url()
            .clone();
        self.ensure_bound_origin(&authorized_url)
            .map_err(map_authorization_error)?;
        lease.ensure_current().map_err(map_authorization_error)?;

        let handshake = async {
            let response = authorized
                .upgrade()
                .protocols([LIVE_SUBPROTOCOL])
                .web_socket_config({
                    let mut config = tungstenite::protocol::WebSocketConfig::default();
                    config.read_buffer_size = LIVE_READ_BUFFER_BYTES;
                    config.write_buffer_size = LIVE_WRITE_BUFFER_BYTES;
                    config.max_write_buffer_size = LIVE_MAX_WRITE_BUFFER_BYTES;
                    config.max_message_size = Some(MAX_BINARY_MESSAGE_BYTES);
                    config.max_frame_size = Some(MAX_BINARY_MESSAGE_BYTES);
                    config.accept_unmasked_frames = false;
                    config
                })
                .send()
                .await?;
            response.into_websocket().await
        };
        let websocket = tokio::select! {
            biased;
            _ = lease.cancelled() => {
                return Err(AuthenticatedLiveError::AccountChanged);
            }
            result = tokio::time::timeout(LIVE_CONNECT_TIMEOUT, handshake) => {
                match result {
                    Ok(Ok(websocket)) => websocket,
                    Ok(Err(error)) => return Err(map_connect_error(error)),
                    Err(_) => return Err(AuthenticatedLiveError::Timeout),
                }
            }
        };
        lease.ensure_current().map_err(map_authorization_error)?;

        let (commands, command_receiver) = mpsc::channel(MAX_PENDING_COMMANDS);
        let (event_sender, events) = mpsc::channel(MAX_PENDING_EVENTS);
        let (terminal_sender, terminal) = watch::channel(None);
        tauri::async_runtime::spawn(run_live_actor(
            websocket,
            lease,
            command_receiver,
            event_sender,
            terminal_sender,
        ));
        Ok(AuthenticatedLiveConnection {
            commands,
            events,
            terminal,
        })
    }
}

pub(super) fn bounded_live_client() -> Result<Client, reqwest::Error> {
    Client::builder()
        .connect_timeout(Duration::from_secs(LIVE_CONNECT_TIMEOUT_SECONDS))
        .redirect(reqwest::redirect::Policy::none())
        .no_proxy()
        .http1_only()
        .build()
}

fn resolve_authenticated_live_endpoint(
    approved_live_origin: &str,
) -> Result<Url, AuthenticatedLiveError> {
    // Authenticated live traffic is plaintext only across the OS loopback
    // boundary. Private-network development overrides remain valid for
    // unauthenticated connector setup, but never relax this credentialed path.
    let normalized = super::super::config::validate_base_url(approved_live_origin, false)
        .map_err(|_| AuthenticatedLiveError::InvalidOrigin)?;
    let endpoint = Url::parse(&normalized).map_err(|_| AuthenticatedLiveError::InvalidOrigin)?;
    let scheme = match endpoint.scheme() {
        "https" => "wss",
        "http" => "ws",
        _ => return Err(AuthenticatedLiveError::InvalidOrigin),
    };
    finalize_live_endpoint(endpoint, scheme)
}

fn finalize_live_endpoint(mut endpoint: Url, scheme: &str) -> Result<Url, AuthenticatedLiveError> {
    endpoint
        .set_scheme(scheme)
        .map_err(|_| AuthenticatedLiveError::InvalidOrigin)?;
    endpoint.set_path(LIVE_PATH);
    endpoint.set_query(None);
    endpoint.set_fragment(None);
    Ok(endpoint)
}

async fn run_live_actor(
    mut websocket: WebSocket,
    lease: SessionLease,
    mut commands: mpsc::Receiver<LiveCommand>,
    events: mpsc::Sender<Result<AuthenticatedLiveMessage, AuthenticatedLiveError>>,
    terminal: watch::Sender<Option<Result<(), AuthenticatedLiveError>>>,
) {
    let result = loop {
        tokio::select! {
            biased;
            _ = lease.cancelled() => {
                break Err(AuthenticatedLiveError::AccountChanged);
            }
            command = commands.recv() => {
                let Some(command) = command else {
                    break Ok(());
                };
                match command {
                    LiveCommand::Send { message, acknowledgement } => {
                        let outbound = match outbound_message(message) {
                            Ok(message) => message,
                            Err(error) => {
                                let _ = acknowledgement.send(Err(error));
                                continue;
                            }
                        };
                        let send_result = tokio::select! {
                            biased;
                            _ = lease.cancelled() => {
                                Err(AuthenticatedLiveError::AccountChanged)
                            }
                            result = tokio::time::timeout(
                                LIVE_SEND_TIMEOUT,
                                websocket.send(outbound),
                            ) => {
                                match result {
                                    Ok(Ok(())) => Ok(()),
                                    Ok(Err(_)) => Err(AuthenticatedLiveError::Transport),
                                    Err(_) => Err(AuthenticatedLiveError::Timeout),
                                }
                            }
                        };
                        let _ = acknowledgement.send(send_result);
                        if let Err(error) = send_result {
                            break Err(error);
                        }
                    }
                    LiveCommand::Close { acknowledgement } => {
                        let close_result = tokio::select! {
                            biased;
                            _ = lease.cancelled() => {
                                Err(AuthenticatedLiveError::AccountChanged)
                            }
                            result = tokio::time::timeout(
                                LIVE_CLOSE_TIMEOUT,
                                SinkExt::close(&mut websocket),
                            ) => {
                                match result {
                                    Ok(Ok(())) => Ok(()),
                                    Ok(Err(_)) => Err(AuthenticatedLiveError::Transport),
                                    Err(_) => Err(AuthenticatedLiveError::Timeout),
                                }
                            }
                        };
                        let _ = acknowledgement.send(close_result);
                        break close_result;
                    }
                }
            }
            incoming = websocket.next() => {
                match incoming {
                    Some(Ok(Message::Text(text))) => {
                        if text.len() > MAX_TEXT_MESSAGE_BYTES {
                            break Err(AuthenticatedLiveError::MessageTooLarge);
                        }
                        if let Err(error) =
                            publish_event(&events, AuthenticatedLiveMessage::Text(text))
                        {
                            break error;
                        }
                    }
                    Some(Ok(Message::Binary(bytes))) => {
                        if bytes.len() > MAX_BINARY_MESSAGE_BYTES {
                            break Err(AuthenticatedLiveError::MessageTooLarge);
                        }
                        if let Err(error) =
                            publish_event(&events, AuthenticatedLiveMessage::Binary(bytes.to_vec()))
                        {
                            break error;
                        }
                    }
                    Some(Ok(Message::Ping(_) | Message::Pong(_))) => {}
                    Some(Ok(Message::Close { .. })) | None => break Ok(()),
                    Some(Err(_)) => break Err(AuthenticatedLiveError::Transport),
                }
            }
        }
    };

    terminal.send_replace(Some(result));
    if let Err(error) = result {
        let _ = events.try_send(Err(error));
    }
}

fn publish_event(
    events: &mpsc::Sender<Result<AuthenticatedLiveMessage, AuthenticatedLiveError>>,
    message: AuthenticatedLiveMessage,
) -> Result<(), Result<(), AuthenticatedLiveError>> {
    match events.try_send(Ok(message)) {
        Ok(()) => Ok(()),
        Err(mpsc::error::TrySendError::Full(_)) => Err(Err(AuthenticatedLiveError::Backpressure)),
        Err(mpsc::error::TrySendError::Closed(_)) => Err(Ok(())),
    }
}

fn validate_outbound(message: &AuthenticatedLiveMessage) -> Result<(), AuthenticatedLiveError> {
    match message {
        AuthenticatedLiveMessage::Text(text) if text.len() > MAX_TEXT_MESSAGE_BYTES => {
            Err(AuthenticatedLiveError::MessageTooLarge)
        }
        AuthenticatedLiveMessage::Binary(bytes) if bytes.len() > MAX_BINARY_MESSAGE_BYTES => {
            Err(AuthenticatedLiveError::MessageTooLarge)
        }
        _ => Ok(()),
    }
}

fn outbound_message(message: AuthenticatedLiveMessage) -> Result<Message, AuthenticatedLiveError> {
    validate_outbound(&message)?;
    Ok(match message {
        AuthenticatedLiveMessage::Text(text) => Message::Text(text),
        AuthenticatedLiveMessage::Binary(bytes) => Message::Binary(bytes.into()),
    })
}

fn map_connect_error(error: reqwest_websocket::Error) -> AuthenticatedLiveError {
    match error {
        reqwest_websocket::Error::Handshake(HandshakeError::UnexpectedStatusCode(status))
            if status == StatusCode::UNAUTHORIZED =>
        {
            AuthenticatedLiveError::SignInRequired
        }
        reqwest_websocket::Error::Handshake(HandshakeError::UnexpectedStatusCode(status))
            if status == StatusCode::FORBIDDEN =>
        {
            AuthenticatedLiveError::AccessDenied
        }
        reqwest_websocket::Error::Handshake(
            HandshakeError::ExpectedAProtocol | HandshakeError::UnexpectedProtocol { .. },
        ) => AuthenticatedLiveError::ProtocolRejected,
        reqwest_websocket::Error::Handshake(_) => AuthenticatedLiveError::HandshakeRejected,
        reqwest_websocket::Error::Reqwest(error) if error.is_timeout() => {
            AuthenticatedLiveError::Timeout
        }
        _ => AuthenticatedLiveError::Transport,
    }
}

fn map_authorization_error(error: RequestAuthorizationError) -> AuthenticatedLiveError {
    match error {
        RequestAuthorizationError::Unavailable => AuthenticatedLiveError::AuthorizationUnavailable,
        RequestAuthorizationError::InvalidToken => AuthenticatedLiveError::InvalidToken,
        RequestAuthorizationError::AccountChanged => AuthenticatedLiveError::AccountChanged,
    }
}

#[cfg(test)]
mod tests;
