use std::env;
use std::process::ExitCode;

use yap_server_orchestrator::{
    parse_supervised_service_arguments, run_supervised_service, OrchestratorError,
    SupervisedServiceConfig,
};

#[tokio::main]
async fn main() -> ExitCode {
    match run_from_command_line().await {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("Yap provider supervisor failed: {error}");
            ExitCode::FAILURE
        }
    }
}

async fn run_from_command_line() -> Result<(), OrchestratorError> {
    let config = parse_supervised_service_arguments(env::args_os().skip(1))?;
    run_until_shutdown_signal(config).await
}

#[cfg(unix)]
async fn run_until_shutdown_signal(
    config: SupervisedServiceConfig,
) -> Result<(), OrchestratorError> {
    use tokio::signal::unix::{signal, SignalKind};

    let mut interrupt = signal(SignalKind::interrupt())?;
    let mut terminate = signal(SignalKind::terminate())?;
    run_supervised_service(config, async move {
        tokio::select! {
            _ = interrupt.recv() => {}
            _ = terminate.recv() => {}
        }
    })
    .await
}

#[cfg(windows)]
async fn run_until_shutdown_signal(
    config: SupervisedServiceConfig,
) -> Result<(), OrchestratorError> {
    use tokio::signal::windows::{ctrl_break, ctrl_c, ctrl_close, ctrl_shutdown};

    let mut control_break = ctrl_break()?;
    let mut control_c = ctrl_c()?;
    let mut control_close = ctrl_close()?;
    let mut control_shutdown = ctrl_shutdown()?;
    run_supervised_service(config, async move {
        tokio::select! {
            _ = control_break.recv() => {}
            _ = control_c.recv() => {}
            _ = control_close.recv() => {}
            _ = control_shutdown.recv() => {}
        }
    })
    .await
}
