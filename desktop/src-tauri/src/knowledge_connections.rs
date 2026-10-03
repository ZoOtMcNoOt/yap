use crate::server_connector::{
    knowledge_connections::{ConnectionsError, ConnectionsRequest, ConnectionsResponse},
    ServerConnector,
};
use std::sync::Mutex;

static REQUEST: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(1);
static CANCELLATION: Mutex<Option<(String, tokio::sync::oneshot::Sender<()>)>> = Mutex::new(None);

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AuthorizedConnectionsResponse {
    authority_revision: String,
    response: ConnectionsResponse,
}

fn request_identity(value: &str) -> Result<String, ConnectionsError> {
    if value.len() == 36
        && value.bytes().enumerate().all(|(i, c)| {
            if [8, 13, 18, 23].contains(&i) {
                c == b'-'
            } else {
                c.is_ascii_digit() || (b'a'..=b'f').contains(&c)
            }
        })
    {
        Ok(value.to_owned())
    } else {
        Err(ConnectionsError::new("invalid", false))
    }
}

fn validate_authority(expected: &str, current: &str) -> Result<(), ConnectionsError> {
    if expected == current {
        Ok(())
    } else {
        Err(ConnectionsError::new("identityChanged", false))
    }
}
struct RequestCancellation(String);
impl Drop for RequestCancellation {
    fn drop(&mut self) {
        let mut cancellation = CANCELLATION
            .lock()
            .expect("knowledge cancellation poisoned");
        if cancellation.as_ref().is_some_and(|(id, _)| *id == self.0) {
            *cancellation = None;
        }
    }
}

#[tauri::command]
pub(crate) async fn knowledge_connections(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    request_id: String,
    request: ConnectionsRequest,
    authority_revision: String,
) -> Result<AuthorizedConnectionsResponse, ConnectionsError> {
    crate::authorization::ensure_main(&window)
        .map_err(|_| ConnectionsError::new("denied", false))?;
    let id = request_identity(&request_id)?;
    let _permit = REQUEST
        .try_acquire()
        .map_err(|_| ConnectionsError::new("busy", true))?;
    let lease = connector
        .knowledge_connections_connection_lease()
        .map_err(|_| ConnectionsError::new("identityChanged", false))?
        .ok_or_else(|| ConnectionsError::new("unavailable", true))?;
    let revision = lease.authority_revision();
    validate_authority(&authority_revision, &revision)?;
    let (cancel, cancelled) = tokio::sync::oneshot::channel();
    *CANCELLATION
        .lock()
        .expect("knowledge cancellation poisoned") = Some((id.clone(), cancel));
    let _cancellation = RequestCancellation(id);
    let result = execute_cancellable(lease.client(), &request, cancelled).await?;
    connector
        .with_current_knowledge_connections_lease(&lease, || AuthorizedConnectionsResponse {
            authority_revision: revision,
            response: result,
        })
        .map_err(|_| ConnectionsError::new("identityChanged", false))
}

async fn execute_cancellable(
    client: &crate::server_connector::knowledge_connections::ConnectionsClient,
    request: &ConnectionsRequest,
    cancelled: tokio::sync::oneshot::Receiver<()>,
) -> Result<ConnectionsResponse, ConnectionsError> {
    tokio::select! {
        result = tokio::time::timeout(std::time::Duration::from_secs(20), client.execute(request)) => result.map_err(|_| ConnectionsError::new("unavailable", true))?,
        _ = cancelled => Err(ConnectionsError::new("cancelled", false)),
    }
}

#[tauri::command]
pub(crate) fn cancel_knowledge_connections(
    window: tauri::WebviewWindow,
    request_id: String,
) -> Result<(), ConnectionsError> {
    crate::authorization::ensure_main(&window)
        .map_err(|_| ConnectionsError::new("denied", false))?;
    let id = request_identity(&request_id)?;
    let mut cancellation = CANCELLATION
        .lock()
        .expect("knowledge cancellation poisoned");
    if cancellation
        .as_ref()
        .is_some_and(|(active, _)| *active == id)
    {
        if let Some((_, sender)) = cancellation.take() {
            let _ = sender.send(());
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cancellation_drops_an_in_flight_authenticated_read_before_it_returns_data() {
        use crate::server_connector::{
            knowledge_connections::ConnectionsClient, AuthenticatedRequestDispatcher,
        };
        use std::{io::Read, net::TcpListener, sync::mpsc, thread, time::Duration};
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let address = listener.local_addr().unwrap();
        let (started, entered) = mpsc::sync_channel(1);
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(3)))
                .unwrap();
            let mut incoming = Vec::new();
            let mut bytes = [0u8; 4096];
            loop {
                let count = stream.read(&mut bytes).unwrap();
                incoming.extend_from_slice(&bytes[..count]);
                if incoming.windows(4).any(|w| w == b"\r\n\r\n") {
                    break;
                }
                assert!(count > 0);
            }
            started.send(()).unwrap();
            // Dropping the request future closes the uncompleted HTTP read.
            assert_eq!(stream.read(&mut bytes).unwrap(), 0);
        });
        let client = ConnectionsClient::new(
            AuthenticatedRequestDispatcher::fixed(reqwest::Client::new(), "private-token"),
            &format!("http://{address}"),
        )
        .unwrap();
        tauri::async_runtime::block_on(async move {
            let (cancel, cancelled) = tokio::sync::oneshot::channel();
            let request = ConnectionsRequest::Browse {
                search: String::new(),
            };
            let read = execute_cancellable(&client, &request, cancelled);
            let signal = async move {
                tokio::task::spawn_blocking(move || entered.recv_timeout(Duration::from_secs(3)))
                    .await
                    .unwrap()
                    .unwrap();
                cancel.send(()).unwrap();
            };
            let (result, _) = tokio::join!(read, signal);
            assert_eq!(
                result.unwrap_err(),
                ConnectionsError::new("cancelled", false)
            );
        });
        server.join().unwrap();
    }

    #[test]
    fn private_search_and_navigation_cannot_retarget_a_changed_account_or_server() {
        assert!(validate_authority("7", "7").is_ok());
        for revision in ["", "6", "07"] {
            assert_eq!(
                validate_authority(revision, "7"),
                Err(ConnectionsError::new("identityChanged", false))
            );
        }
        assert!(validate_authority("7", "8").is_err());
    }
}
