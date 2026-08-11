use std::future::Future;

use crate::agent_admission_config::AgentAdmissionBrokerConfig;
use crate::error::OrchestratorError;

#[cfg(unix)]
use std::fs;
#[cfg(unix)]
use std::path::{Path, PathBuf};
#[cfg(unix)]
use std::sync::Arc;
#[cfg(unix)]
use std::time::{Duration, Instant};

#[cfg(unix)]
use tokio::io::{AsyncBufRead, AsyncBufReadExt, AsyncWriteExt, BufReader};
#[cfg(unix)]
use tokio::net::{UnixListener, UnixStream};
#[cfg(unix)]
use tokio::sync::{Mutex, Semaphore};
#[cfg(unix)]
use tokio::task::JoinSet;
#[cfg(unix)]
use tokio::time::{interval, timeout, MissedTickBehavior};

#[cfg(unix)]
use crate::agent_admission::AgentAdmissionScheduler;
#[cfg(unix)]
use crate::agent_admission_protocol::{
    agent_admission_busy_response, process_agent_admission_request, MAXIMUM_REQUEST_BYTES,
};
#[cfg(unix)]
use crate::agent_work::ExecutionRoute;
#[cfg(unix)]
use crate::lifecycle::{ProviderService, ServiceSnapshot};
#[cfg(unix)]
use crate::state_snapshot::read_private_snapshot;

#[cfg(unix)]
const PROVIDER_OBSERVATION_INTERVAL: Duration = Duration::from_millis(100);
#[cfg(unix)]
const CONNECTION_IO_TIMEOUT: Duration = Duration::from_secs(2);
#[cfg(unix)]
const MAXIMUM_CONNECTIONS: usize = 64;

#[cfg(unix)]
pub async fn run_agent_admission_broker<F>(
    config: AgentAdmissionBrokerConfig,
    shutdown: F,
) -> Result<(), OrchestratorError>
where
    F: Future<Output = ()> + Send,
{
    let bound_socket = BoundSocket::bind(config.socket_path())?;
    let scheduler = Arc::new(Mutex::new(config.new_scheduler()?));
    let state_paths = Arc::new(ProviderStatePaths {
        rapid: config.rapid_state_path().to_owned(),
        complex: config.complex_state_path().to_owned(),
    });
    let started_at = Instant::now();
    refresh_provider_states(&scheduler, &state_paths, started_at.elapsed()).await;

    let permits = Arc::new(Semaphore::new(MAXIMUM_CONNECTIONS));
    let mut handlers = JoinSet::new();
    let mut provider_tick = interval(PROVIDER_OBSERVATION_INTERVAL);
    provider_tick.set_missed_tick_behavior(MissedTickBehavior::Skip);
    tokio::pin!(shutdown);

    loop {
        tokio::select! {
            _ = &mut shutdown => break,
            _ = provider_tick.tick() => {
                refresh_provider_states(&scheduler, &state_paths, started_at.elapsed()).await;
            }
            completed = handlers.join_next(), if !handlers.is_empty() => {
                if let Some(Err(error)) = completed {
                    return Err(OrchestratorError::new(format!(
                        "admission connection task failed: {error}"
                    )));
                }
            }
            accepted = bound_socket.listener.accept() => {
                let (stream, _) = accepted?;
                let Ok(permit) = permits.clone().try_acquire_owned() else {
                    let _ = stream.try_write(&agent_admission_busy_response());
                    continue;
                };
                let scheduler = Arc::clone(&scheduler);
                let state_paths = Arc::clone(&state_paths);
                handlers.spawn(async move {
                    let _permit = permit;
                    handle_connection(stream, scheduler, state_paths, started_at).await
                });
            }
        }
    }

    handlers.abort_all();
    while handlers.join_next().await.is_some() {}
    Ok(())
}

#[cfg(not(unix))]
pub async fn run_agent_admission_broker<F>(
    _config: AgentAdmissionBrokerConfig,
    _shutdown: F,
) -> Result<(), OrchestratorError>
where
    F: Future<Output = ()> + Send,
{
    Err(OrchestratorError::new(
        "agent admission broker requires a Unix-domain socket host",
    ))
}

#[cfg(unix)]
async fn handle_connection(
    stream: UnixStream,
    scheduler: Arc<Mutex<AgentAdmissionScheduler>>,
    state_paths: Arc<ProviderStatePaths>,
    started_at: Instant,
) -> Result<(), OrchestratorError> {
    let (reader, mut writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let request = timeout(CONNECTION_IO_TIMEOUT, read_bounded_request(&mut reader))
        .await
        .map_err(|_| OrchestratorError::new("admission request read timed out"))??;

    let observed_at = started_at.elapsed();
    let observations = read_provider_states(&state_paths);
    let response = {
        let mut scheduler = scheduler.lock().await;
        apply_provider_states(&mut scheduler, observations);
        process_agent_admission_request(&mut scheduler, &request, observed_at)
    };
    timeout(CONNECTION_IO_TIMEOUT, writer.write_all(&response))
        .await
        .map_err(|_| OrchestratorError::new("admission response write timed out"))??;
    timeout(CONNECTION_IO_TIMEOUT, writer.shutdown())
        .await
        .map_err(|_| OrchestratorError::new("admission response shutdown timed out"))??;
    Ok(())
}

#[cfg(unix)]
async fn read_bounded_request<R>(reader: &mut R) -> Result<Vec<u8>, OrchestratorError>
where
    R: AsyncBufRead + Unpin,
{
    let mut request = Vec::new();
    loop {
        let available = reader.fill_buf().await?;
        if available.is_empty() {
            return Ok(request);
        }
        let through_newline = available
            .iter()
            .position(|byte| *byte == b'\n')
            .map_or(available.len(), |index| index + 1);
        let remaining = MAXIMUM_REQUEST_BYTES + 1 - request.len();
        let consumed = through_newline.min(remaining);
        request.extend_from_slice(&available[..consumed]);
        reader.consume(consumed);
        if request.ends_with(b"\n") || request.len() > MAXIMUM_REQUEST_BYTES {
            return Ok(request);
        }
    }
}

#[cfg(unix)]
async fn refresh_provider_states(
    scheduler: &Arc<Mutex<AgentAdmissionScheduler>>,
    paths: &ProviderStatePaths,
    observed_at: Duration,
) {
    let observations = read_provider_states(paths);
    let mut scheduler = scheduler.lock().await;
    apply_provider_states(&mut scheduler, observations);
    scheduler.dispatch(observed_at);
}

#[cfg(unix)]
fn read_provider_states(paths: &ProviderStatePaths) -> [ProviderStateObservation; 2] {
    [
        ProviderStateObservation::read(ProviderService::RapidAutomation, &paths.rapid),
        ProviderStateObservation::read(ProviderService::ComplexOrchestration, &paths.complex),
    ]
}

#[cfg(unix)]
fn apply_provider_states(
    scheduler: &mut AgentAdmissionScheduler,
    observations: [ProviderStateObservation; 2],
) {
    for observation in observations {
        let route = ExecutionRoute::from_provider(observation.expected_service);
        match observation.snapshot {
            Some(snapshot) if snapshot.service == observation.expected_service => {
                let _ = scheduler.observe_provider(&snapshot);
            }
            _ => {
                let _ = scheduler.mark_provider_unavailable(route);
            }
        }
    }
}

#[cfg(unix)]
struct ProviderStatePaths {
    rapid: PathBuf,
    complex: PathBuf,
}

#[cfg(unix)]
struct ProviderStateObservation {
    expected_service: ProviderService,
    snapshot: Option<ServiceSnapshot>,
}

#[cfg(unix)]
impl ProviderStateObservation {
    fn read(expected_service: ProviderService, path: &Path) -> Self {
        Self {
            expected_service,
            snapshot: read_private_snapshot(path).ok(),
        }
    }
}

#[cfg(unix)]
struct BoundSocket {
    listener: UnixListener,
    path: PathBuf,
    device: u64,
    inode: u64,
}

#[cfg(unix)]
impl BoundSocket {
    fn bind(path: &Path) -> Result<Self, OrchestratorError> {
        use std::os::unix::fs::{FileTypeExt, MetadataExt, PermissionsExt};

        let parent = path
            .parent()
            .ok_or_else(|| OrchestratorError::new("admission socket parent is invalid"))?;
        if parent.canonicalize()? != parent {
            return Err(OrchestratorError::new(
                "admission socket parent must be canonical",
            ));
        }
        let parent_metadata = fs::symlink_metadata(parent)?;
        if !parent_metadata.file_type().is_dir()
            || parent_metadata.file_type().is_symlink()
            || parent_metadata.permissions().mode() & 0o077 != 0
            || parent_metadata.uid() != unsafe { libc::geteuid() }
        {
            return Err(OrchestratorError::new(
                "admission socket parent must be an owner-private service directory",
            ));
        }
        match fs::symlink_metadata(path) {
            Ok(_) => {
                return Err(OrchestratorError::new(
                    "admission socket destination already exists",
                ));
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        let listener = UnixListener::bind(path)?;
        fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
        let metadata = fs::symlink_metadata(path)?;
        if !metadata.file_type().is_socket()
            || metadata.permissions().mode() & 0o777 != 0o600
            || metadata.uid() != unsafe { libc::geteuid() }
        {
            let _ = fs::remove_file(path);
            return Err(OrchestratorError::new(
                "admission socket identity is invalid",
            ));
        }
        fs::File::open(parent)?.sync_all()?;
        Ok(Self {
            listener,
            path: path.to_owned(),
            device: metadata.dev(),
            inode: metadata.ino(),
        })
    }
}

#[cfg(unix)]
impl Drop for BoundSocket {
    fn drop(&mut self) {
        use std::os::unix::fs::MetadataExt;

        if fs::symlink_metadata(&self.path)
            .is_ok_and(|metadata| metadata.dev() == self.device && metadata.ino() == self.inode)
        {
            let _ = fs::remove_file(&self.path);
            if let Some(parent) = self.path.parent() {
                let _ = fs::File::open(parent).and_then(|directory| directory.sync_all());
            }
        }
    }
}
