use std::env;
use std::process::ExitCode;

use yap_server_orchestrator::{
    parse_agent_admission_arguments, run_agent_admission_broker, OrchestratorError,
};

#[tokio::main]
async fn main() -> ExitCode {
    match run_from_command_line().await {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("Yap agent admission broker failed: {error}");
            ExitCode::FAILURE
        }
    }
}

async fn run_from_command_line() -> Result<(), OrchestratorError> {
    let config = parse_agent_admission_arguments(env::args_os().skip(1))?;
    run_until_shutdown_signal(config).await
}

#[cfg(unix)]
async fn run_until_shutdown_signal(
    config: yap_server_orchestrator::AgentAdmissionBrokerConfig,
) -> Result<(), OrchestratorError> {
    use tokio::signal::unix::{signal, SignalKind};

    let mut interrupt = signal(SignalKind::interrupt())?;
    let mut terminate = signal(SignalKind::terminate())?;
    run_agent_admission_broker(config, async move {
        tokio::select! {
            _ = interrupt.recv() => {}
            _ = terminate.recv() => {}
        }
    })
    .await
}

#[cfg(not(unix))]
async fn run_until_shutdown_signal(
    config: yap_server_orchestrator::AgentAdmissionBrokerConfig,
) -> Result<(), OrchestratorError> {
    run_agent_admission_broker(config, std::future::pending()).await
}
