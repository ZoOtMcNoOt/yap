use std::future::Future;
use std::time::Duration;

use tokio::process::{Child, Command};
use tokio::time::{sleep, timeout, Instant, MissedTickBehavior};

use crate::config::{CommandSpec, SupervisedServiceConfig};
use crate::error::OrchestratorError;
use crate::lifecycle::{LifecycleTracker, RestartDecision};
use crate::readiness::probe_exact_service;
use crate::state_snapshot::write_private_snapshot;

const STARTUP_TIMEOUT: Duration = Duration::from_secs(600);
const STARTUP_POLL_INTERVAL: Duration = Duration::from_millis(100);
const READY_POLL_INTERVAL: Duration = Duration::from_secs(1);
const MAXIMUM_CONSECUTIVE_HEALTH_FAILURES: u8 = 3;
const GRACEFUL_STOP_TIMEOUT: Duration = Duration::from_secs(10);
const FORCED_STOP_TIMEOUT: Duration = Duration::from_secs(5);

enum RuntimeObservation {
    Ready,
    Lost,
    Shutdown,
}

enum RestartOutcome {
    Restart,
    Shutdown,
    Exhausted,
}

pub async fn run_supervised_service<F>(
    config: SupervisedServiceConfig,
    shutdown: F,
) -> Result<(), OrchestratorError>
where
    F: Future<Output = ()> + Send,
{
    let lifecycle_started_at = Instant::now();
    let mut tracker = LifecycleTracker::new(
        config.service(),
        config.profile_id().to_owned(),
        config.profile_sha256().to_owned(),
        config.candidate_lock_sha256().to_owned(),
    );
    tokio::pin!(shutdown);

    loop {
        tracker.record_start()?;
        write_private_snapshot(config.state_path(), tracker.snapshot())?;
        let child = spawn_provider_child(config.command());
        let mut child = match child {
            Ok(child) => child,
            Err(_error) => {
                match restart_after_failure(
                    &config,
                    &mut tracker,
                    lifecycle_started_at.elapsed(),
                    &mut shutdown,
                )
                .await?
                {
                    RestartOutcome::Restart => continue,
                    RestartOutcome::Shutdown => return Ok(()),
                    RestartOutcome::Exhausted => {
                        return Err(OrchestratorError::new(
                            "provider service restart policy was exhausted",
                        ));
                    }
                }
            }
        };

        match wait_for_readiness(&config, &mut child, &mut shutdown).await? {
            RuntimeObservation::Shutdown => {
                return stop_child(&config, &mut tracker, &mut child).await;
            }
            RuntimeObservation::Lost => {
                match restart_after_failure(
                    &config,
                    &mut tracker,
                    lifecycle_started_at.elapsed(),
                    &mut shutdown,
                )
                .await?
                {
                    RestartOutcome::Restart => continue,
                    RestartOutcome::Shutdown => return Ok(()),
                    RestartOutcome::Exhausted => {
                        return Err(OrchestratorError::new(
                            "provider service restart policy was exhausted",
                        ));
                    }
                }
            }
            RuntimeObservation::Ready => {}
        }

        tracker.record_ready()?;
        if let Err(error) = write_private_snapshot(config.state_path(), tracker.snapshot()) {
            let _ = terminate_and_reap(&mut child).await;
            return Err(error);
        }
        match monitor_ready_service(&config, &mut child, &mut shutdown).await? {
            RuntimeObservation::Shutdown => {
                return stop_child(&config, &mut tracker, &mut child).await;
            }
            RuntimeObservation::Lost => {
                match restart_after_failure(
                    &config,
                    &mut tracker,
                    lifecycle_started_at.elapsed(),
                    &mut shutdown,
                )
                .await?
                {
                    RestartOutcome::Restart => {}
                    RestartOutcome::Shutdown => return Ok(()),
                    RestartOutcome::Exhausted => {
                        return Err(OrchestratorError::new(
                            "provider service restart policy was exhausted",
                        ));
                    }
                }
            }
            RuntimeObservation::Ready => {
                return Err(OrchestratorError::new(
                    "provider service monitor returned an invalid state",
                ));
            }
        }
    }
}

fn spawn_provider_child(command_spec: &CommandSpec) -> Result<Child, OrchestratorError> {
    command_spec.validate_for_spawn()?;
    let mut command = Command::new(command_spec.program());
    command
        .args(command_spec.arguments())
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::inherit())
        .stderr(std::process::Stdio::inherit())
        .kill_on_drop(true);
    configure_child_process_group(&mut command);
    command
        .spawn()
        .map_err(|_| OrchestratorError::new("provider launcher could not be started"))
}

#[cfg(unix)]
fn configure_child_process_group(command: &mut Command) {
    use std::os::unix::process::CommandExt;
    command.as_std_mut().process_group(0);
}

#[cfg(not(unix))]
fn configure_child_process_group(_command: &mut Command) {}

async fn wait_for_readiness<F>(
    config: &SupervisedServiceConfig,
    child: &mut Child,
    shutdown: &mut std::pin::Pin<&mut F>,
) -> Result<RuntimeObservation, OrchestratorError>
where
    F: Future<Output = ()> + Send,
{
    let deadline = sleep(STARTUP_TIMEOUT);
    tokio::pin!(deadline);
    let mut interval = tokio::time::interval(STARTUP_POLL_INTERVAL);
    interval.set_missed_tick_behavior(MissedTickBehavior::Skip);
    loop {
        tokio::select! {
            _ = &mut *shutdown => return Ok(RuntimeObservation::Shutdown),
            status = child.wait() => {
                status.map_err(|_| OrchestratorError::new("provider launcher could not be reaped"))?;
                return Ok(RuntimeObservation::Lost);
            }
            _ = &mut deadline => {
                terminate_and_reap(child).await?;
                return Ok(RuntimeObservation::Lost);
            }
            _ = interval.tick() => {
                if probe_exact_service(config).await {
                    return Ok(RuntimeObservation::Ready);
                }
            }
        }
    }
}

async fn monitor_ready_service<F>(
    config: &SupervisedServiceConfig,
    child: &mut Child,
    shutdown: &mut std::pin::Pin<&mut F>,
) -> Result<RuntimeObservation, OrchestratorError>
where
    F: Future<Output = ()> + Send,
{
    let mut failures = 0_u8;
    let mut interval = tokio::time::interval(READY_POLL_INTERVAL);
    interval.set_missed_tick_behavior(MissedTickBehavior::Skip);
    interval.tick().await;
    loop {
        tokio::select! {
            _ = &mut *shutdown => return Ok(RuntimeObservation::Shutdown),
            status = child.wait() => {
                status.map_err(|_| OrchestratorError::new("provider launcher could not be reaped"))?;
                return Ok(RuntimeObservation::Lost);
            }
            _ = interval.tick() => {
                if probe_exact_service(config).await {
                    failures = 0;
                } else {
                    failures = failures.saturating_add(1);
                    if failures >= MAXIMUM_CONSECUTIVE_HEALTH_FAILURES {
                        terminate_and_reap(child).await?;
                        return Ok(RuntimeObservation::Lost);
                    }
                }
            }
        }
    }
}

async fn restart_after_failure<F>(
    config: &SupervisedServiceConfig,
    tracker: &mut LifecycleTracker,
    observed_at: Duration,
    shutdown: &mut std::pin::Pin<&mut F>,
) -> Result<RestartOutcome, OrchestratorError>
where
    F: Future<Output = ()> + Send,
{
    match tracker.record_unexpected_exit(observed_at) {
        RestartDecision::Exhausted => {
            write_private_snapshot(config.state_path(), tracker.snapshot())?;
            Ok(RestartOutcome::Exhausted)
        }
        RestartDecision::After(backoff) => {
            write_private_snapshot(config.state_path(), tracker.snapshot())?;
            tokio::select! {
                _ = &mut *shutdown => {
                    stop_without_child(config, tracker)?;
                    Ok(RestartOutcome::Shutdown)
                }
                _ = sleep(backoff) => Ok(RestartOutcome::Restart),
            }
        }
    }
}

async fn stop_child(
    config: &SupervisedServiceConfig,
    tracker: &mut LifecycleTracker,
    child: &mut Child,
) -> Result<(), OrchestratorError> {
    tracker.record_stopping()?;
    let state_result = write_private_snapshot(config.state_path(), tracker.snapshot());
    let stop_result = terminate_and_reap(child).await;
    state_result?;
    stop_result?;
    tracker.record_stopped()?;
    write_private_snapshot(config.state_path(), tracker.snapshot())?;
    Ok(())
}

fn stop_without_child(
    config: &SupervisedServiceConfig,
    tracker: &mut LifecycleTracker,
) -> Result<(), OrchestratorError> {
    tracker.record_stopping()?;
    write_private_snapshot(config.state_path(), tracker.snapshot())?;
    tracker.record_stopped()?;
    write_private_snapshot(config.state_path(), tracker.snapshot())?;
    Ok(())
}

async fn terminate_and_reap(child: &mut Child) -> Result<(), OrchestratorError> {
    if child
        .try_wait()
        .map_err(|_| OrchestratorError::new("provider launcher status could not be read"))?
        .is_some()
    {
        return Ok(());
    }
    request_graceful_termination(child)?;
    if let Ok(wait_result) = timeout(GRACEFUL_STOP_TIMEOUT, child.wait()).await {
        wait_result.map_err(|_| OrchestratorError::new("provider launcher could not be reaped"))?;
        return Ok(());
    }
    child
        .start_kill()
        .map_err(|_| OrchestratorError::new("provider launcher could not be killed"))?;
    timeout(FORCED_STOP_TIMEOUT, child.wait())
        .await
        .map_err(|_| OrchestratorError::new("provider launcher did not exit after kill"))?
        .map_err(|_| OrchestratorError::new("provider launcher could not be reaped"))?;
    Ok(())
}

#[cfg(unix)]
fn request_graceful_termination(child: &mut Child) -> Result<(), OrchestratorError> {
    let process_id = child
        .id()
        .ok_or_else(|| OrchestratorError::new("provider launcher identity is unavailable"))?;
    let result = unsafe { libc::kill(process_id as i32, libc::SIGTERM) };
    if result == 0 {
        return Ok(());
    }
    let error = std::io::Error::last_os_error();
    if error.raw_os_error() == Some(libc::ESRCH) {
        return Ok(());
    }
    Err(OrchestratorError::new(
        "provider launcher could not be terminated",
    ))
}

#[cfg(not(unix))]
fn request_graceful_termination(child: &mut Child) -> Result<(), OrchestratorError> {
    child
        .start_kill()
        .map_err(|_| OrchestratorError::new("provider launcher could not be terminated"))
}
