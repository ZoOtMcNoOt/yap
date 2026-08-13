use std::ffi::OsString;
use std::path::{Component, Path, PathBuf};

use crate::agent_admission::{AgentAdmissionScheduler, ProviderRouteIdentity};
use crate::error::OrchestratorError;
use crate::lifecycle::ProviderService;
use crate::service_profile::load_service_profile;

#[derive(Debug)]
pub struct AgentAdmissionBrokerConfig {
    socket_path: PathBuf,
    rapid_state_path: PathBuf,
    complex_state_path: PathBuf,
    rapid_identity: ProviderRouteIdentity,
    complex_identity: ProviderRouteIdentity,
}

impl AgentAdmissionBrokerConfig {
    pub fn socket_path(&self) -> &Path {
        &self.socket_path
    }

    pub fn rapid_state_path(&self) -> &Path {
        &self.rapid_state_path
    }

    pub fn complex_state_path(&self) -> &Path {
        &self.complex_state_path
    }

    pub fn new_scheduler(&self) -> Result<AgentAdmissionScheduler, OrchestratorError> {
        AgentAdmissionScheduler::new(self.rapid_identity.clone(), self.complex_identity.clone())
    }
}

pub fn parse_agent_admission_arguments<I>(
    arguments: I,
) -> Result<AgentAdmissionBrokerConfig, OrchestratorError>
where
    I: IntoIterator<Item = OsString>,
{
    let mut socket_path = None;
    let mut candidate_lock = None;
    let mut rapid_profile = None;
    let mut rapid_profile_sha256 = None;
    let mut rapid_state_path = None;
    let mut complex_profile = None;
    let mut complex_profile_sha256 = None;
    let mut complex_state_path = None;
    let mut values = arguments.into_iter();

    while let Some(flag) = values.next() {
        let flag = flag
            .to_str()
            .ok_or_else(|| OrchestratorError::new("admission control argument is invalid"))?;
        let value = values
            .next()
            .ok_or_else(|| OrchestratorError::new("admission control value is missing"))?;
        match flag {
            "--socket-path" => set_once(&mut socket_path, value, "admission socket")?,
            "--candidate-lock" => set_once(&mut candidate_lock, value, "candidate lock")?,
            "--rapid-profile" => set_once(&mut rapid_profile, value, "rapid profile")?,
            "--rapid-profile-sha256" => {
                set_once(&mut rapid_profile_sha256, value, "rapid profile digest")?
            }
            "--rapid-state-path" => set_once(&mut rapid_state_path, value, "rapid state source")?,
            "--complex-profile" => set_once(&mut complex_profile, value, "complex profile")?,
            "--complex-profile-sha256" => {
                set_once(&mut complex_profile_sha256, value, "complex profile digest")?
            }
            "--complex-state-path" => {
                set_once(&mut complex_state_path, value, "complex state source")?
            }
            _ => {
                return Err(OrchestratorError::new(
                    "admission control argument is unknown",
                ));
            }
        }
    }

    let socket_path = validated_runtime_path(required_path(socket_path, "admission socket")?)?;
    let rapid_state_path =
        validated_runtime_path(required_path(rapid_state_path, "rapid state source")?)?;
    let complex_state_path =
        validated_runtime_path(required_path(complex_state_path, "complex state source")?)?;
    if socket_path == rapid_state_path
        || socket_path == complex_state_path
        || rapid_state_path == complex_state_path
    {
        return Err(OrchestratorError::new(
            "admission runtime paths must be distinct",
        ));
    }
    let candidate_lock = required_path(candidate_lock, "candidate lock")?;
    let rapid_profile_path = required_path(rapid_profile, "rapid profile")?;
    let complex_profile_path = required_path(complex_profile, "complex profile")?;
    let rapid_profile_sha256 = required_text(rapid_profile_sha256, "rapid profile digest")?;
    let complex_profile_sha256 = required_text(complex_profile_sha256, "complex profile digest")?;
    let rapid = load_service_profile(
        &rapid_profile_path,
        &rapid_profile_sha256,
        &candidate_lock,
        ProviderService::RapidAutomation,
    )?;
    let complex = load_service_profile(
        &complex_profile_path,
        &complex_profile_sha256,
        &candidate_lock,
        ProviderService::ComplexOrchestration,
    )?;
    let rapid_identity = ProviderRouteIdentity::new(
        ProviderService::RapidAutomation,
        rapid.profile_sha256().to_owned(),
        rapid.candidate_lock_sha256().to_owned(),
        usize::from(rapid.maximum_sequences()),
    )?;
    let complex_identity = ProviderRouteIdentity::new(
        ProviderService::ComplexOrchestration,
        complex.profile_sha256().to_owned(),
        complex.candidate_lock_sha256().to_owned(),
        usize::from(complex.maximum_sequences()),
    )?;
    AgentAdmissionScheduler::new(rapid_identity.clone(), complex_identity.clone())?;

    Ok(AgentAdmissionBrokerConfig {
        socket_path,
        rapid_state_path,
        complex_state_path,
        rapid_identity,
        complex_identity,
    })
}

fn set_once(
    slot: &mut Option<OsString>,
    value: OsString,
    name: &str,
) -> Result<(), OrchestratorError> {
    if slot.replace(value).is_some() {
        return Err(OrchestratorError::new(format!(
            "{name} was supplied more than once"
        )));
    }
    Ok(())
}

fn required_path(value: Option<OsString>, name: &str) -> Result<PathBuf, OrchestratorError> {
    value
        .map(PathBuf::from)
        .ok_or_else(|| OrchestratorError::new(format!("{name} is required")))
}

fn required_text(value: Option<OsString>, name: &str) -> Result<String, OrchestratorError> {
    value
        .ok_or_else(|| OrchestratorError::new(format!("{name} is required")))?
        .into_string()
        .map_err(|_| OrchestratorError::new(format!("{name} is invalid")))
}

fn validated_runtime_path(path: PathBuf) -> Result<PathBuf, OrchestratorError> {
    if !path.is_absolute()
        || path
            .components()
            .any(|component| matches!(component, Component::CurDir | Component::ParentDir))
    {
        return Err(OrchestratorError::new(
            "admission runtime path must be canonical and absolute",
        ));
    }
    Ok(path)
}
