use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};

use crate::endpoint::NumericLoopbackEndpoint;
use crate::error::OrchestratorError;
use crate::lifecycle::ProviderService;
use crate::state_snapshot::validate_snapshot_path;

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct CommandSpec {
    program: PathBuf,
    arguments: Vec<OsString>,
}

impl CommandSpec {
    pub fn new(program: PathBuf, arguments: Vec<OsString>) -> Result<Self, OrchestratorError> {
        validate_launcher_path(&program)?;
        if arguments
            .iter()
            .any(|value| value.to_string_lossy().contains('\0'))
        {
            return Err(OrchestratorError::new(
                "provider launcher argument is invalid",
            ));
        }
        Ok(Self { program, arguments })
    }

    pub fn program(&self) -> &Path {
        &self.program
    }

    pub fn arguments(&self) -> &[OsString] {
        &self.arguments
    }

    pub(crate) fn validate_for_spawn(&self) -> Result<(), OrchestratorError> {
        validate_launcher_path(&self.program)
    }
}

fn validate_launcher_path(program: &Path) -> Result<(), OrchestratorError> {
    if !program.is_absolute() {
        return Err(OrchestratorError::new(
            "provider launcher path must be absolute",
        ));
    }
    require_canonical_launcher_path(program)?;
    let metadata = fs::symlink_metadata(program).map_err(|_| {
        OrchestratorError::new("provider launcher must be an existing regular file")
    })?;
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err(OrchestratorError::new(
            "provider launcher must be an existing regular file",
        ));
    }
    require_executable_launcher(&metadata)
}

fn require_canonical_launcher_path(program: &Path) -> Result<(), OrchestratorError> {
    use std::path::Component;

    let components = program.components().collect::<Vec<_>>();
    let normalized = components
        .iter()
        .map(|component| component.as_os_str())
        .collect::<PathBuf>();
    if normalized != program
        || components
            .iter()
            .any(|component| matches!(component, Component::CurDir | Component::ParentDir))
    {
        return Err(OrchestratorError::new(
            "provider launcher path must be canonical",
        ));
    }
    for ancestor in program.ancestors().skip(1) {
        if ancestor.as_os_str().is_empty() {
            continue;
        }
        let metadata = fs::symlink_metadata(ancestor)
            .map_err(|_| OrchestratorError::new("provider launcher ancestry must already exist"))?;
        if metadata.file_type().is_symlink() {
            return Err(OrchestratorError::new(
                "provider launcher ancestry must not contain symbolic links",
            ));
        }
    }
    Ok(())
}

#[cfg(unix)]
fn require_executable_launcher(metadata: &fs::Metadata) -> Result<(), OrchestratorError> {
    use std::os::unix::fs::PermissionsExt;
    if metadata.permissions().mode() & 0o111 == 0 {
        return Err(OrchestratorError::new(
            "provider launcher must be executable",
        ));
    }
    Ok(())
}

#[cfg(not(unix))]
fn require_executable_launcher(_metadata: &fs::Metadata) -> Result<(), OrchestratorError> {
    Ok(())
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct SupervisedServiceConfig {
    service: ProviderService,
    endpoint: NumericLoopbackEndpoint,
    expected_model: String,
    state_path: PathBuf,
    command: CommandSpec,
}

impl SupervisedServiceConfig {
    pub fn new(
        service: ProviderService,
        endpoint: NumericLoopbackEndpoint,
        expected_model: String,
        state_path: PathBuf,
        command: CommandSpec,
    ) -> Result<Self, OrchestratorError> {
        if expected_model.is_empty()
            || expected_model.len() > 256
            || expected_model.trim() != expected_model
            || expected_model.chars().any(char::is_control)
        {
            return Err(OrchestratorError::new("provider model identity is invalid"));
        }
        let state_path = validate_snapshot_path(state_path)?;
        Ok(Self {
            service,
            endpoint,
            expected_model,
            state_path,
            command,
        })
    }

    pub fn service(&self) -> ProviderService {
        self.service
    }

    pub fn endpoint(&self) -> NumericLoopbackEndpoint {
        self.endpoint
    }

    pub fn expected_model(&self) -> &str {
        &self.expected_model
    }

    pub fn state_path(&self) -> &Path {
        &self.state_path
    }

    pub fn command(&self) -> &CommandSpec {
        &self.command
    }
}

pub fn parse_supervised_service_arguments<I>(
    arguments: I,
) -> Result<SupervisedServiceConfig, OrchestratorError>
where
    I: IntoIterator<Item = OsString>,
{
    let mut values = arguments.into_iter();
    let mut service = None;
    let mut endpoint = None;
    let mut expected_model = None;
    let mut state_path = None;
    let mut launcher = None;
    let mut launcher_arguments = Vec::new();
    let mut separator_observed = false;

    while let Some(flag) = values.next() {
        let Some(flag) = flag.to_str() else {
            return Err(OrchestratorError::new(
                "supervisor control argument is invalid",
            ));
        };
        if flag == "--" {
            separator_observed = true;
            launcher_arguments.extend(values);
            break;
        }
        let value = values
            .next()
            .ok_or_else(|| OrchestratorError::new("supervisor control value is missing"))?;
        match flag {
            "--service" => set_once(&mut service, value, "provider service")?,
            "--endpoint" => set_once(&mut endpoint, value, "provider endpoint")?,
            "--expected-model" => set_once(&mut expected_model, value, "provider model identity")?,
            "--state-path" => set_once(&mut state_path, value, "service state destination")?,
            "--launcher" => set_once(&mut launcher, value, "provider launcher")?,
            _ => {
                return Err(OrchestratorError::new(
                    "supervisor control argument is unknown",
                ));
            }
        }
    }

    if !separator_observed {
        return Err(OrchestratorError::new(
            "provider launcher arguments must follow --",
        ));
    }
    let service_value = require_text(service, "provider service")?;
    let service = ProviderService::parse(&service_value)?;
    let endpoint_value = require_text(endpoint, "provider endpoint")?;
    let endpoint = NumericLoopbackEndpoint::parse(&endpoint_value)?;
    let expected_model = require_text(expected_model, "provider model identity")?;
    let state_path = PathBuf::from(
        state_path
            .ok_or_else(|| OrchestratorError::new("service state destination is required"))?,
    );
    let launcher = PathBuf::from(
        launcher.ok_or_else(|| OrchestratorError::new("provider launcher is required"))?,
    );
    SupervisedServiceConfig::new(
        service,
        endpoint,
        expected_model,
        state_path,
        CommandSpec::new(launcher, launcher_arguments)?,
    )
}

fn set_once(
    slot: &mut Option<OsString>,
    value: OsString,
    name: &str,
) -> Result<(), OrchestratorError> {
    if slot.replace(value).is_some() {
        return Err(OrchestratorError::new(format!(
            "{name} was supplied more than once",
        )));
    }
    Ok(())
}

fn require_text(value: Option<OsString>, name: &str) -> Result<String, OrchestratorError> {
    let value = value.ok_or_else(|| OrchestratorError::new(format!("{name} is required")))?;
    value
        .into_string()
        .map_err(|_| OrchestratorError::new(format!("{name} is invalid")))
}
