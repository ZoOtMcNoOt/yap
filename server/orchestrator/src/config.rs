use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};

use crate::error::OrchestratorError;
use crate::lifecycle::ProviderService;
use crate::service_profile::{load_service_profile, ServiceProfileIdentity};
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
    profile: ServiceProfileIdentity,
    state_path: PathBuf,
    command: CommandSpec,
}

impl SupervisedServiceConfig {
    pub fn new(
        profile: ServiceProfileIdentity,
        state_path: PathBuf,
        command: CommandSpec,
    ) -> Result<Self, OrchestratorError> {
        let state_path = validate_snapshot_path(state_path)?;
        Ok(Self {
            profile,
            state_path,
            command,
        })
    }

    pub fn service(&self) -> ProviderService {
        self.profile.service()
    }

    pub fn endpoint(&self) -> crate::endpoint::NumericLoopbackEndpoint {
        self.profile.endpoint()
    }

    pub fn expected_model(&self) -> &str {
        self.profile.expected_model()
    }

    pub fn profile_id(&self) -> &str {
        self.profile.profile_id()
    }

    pub fn profile_sha256(&self) -> &str {
        self.profile.profile_sha256()
    }

    pub fn candidate_lock_sha256(&self) -> &str {
        self.profile.candidate_lock_sha256()
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
    let mut profile = None;
    let mut profile_sha256 = None;
    let mut candidate_lock = None;
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
            "--profile" => set_once(&mut profile, value, "provider service profile")?,
            "--profile-sha256" => set_once(
                &mut profile_sha256,
                value,
                "provider service profile digest",
            )?,
            "--candidate-lock" => set_once(&mut candidate_lock, value, "agent candidate lock")?,
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
    let profile_path = PathBuf::from(
        profile.ok_or_else(|| OrchestratorError::new("provider service profile is required"))?,
    );
    let profile_sha256 = require_text(profile_sha256, "provider service profile digest")?;
    let candidate_lock_path = PathBuf::from(
        candidate_lock.ok_or_else(|| OrchestratorError::new("agent candidate lock is required"))?,
    );
    let identity = load_service_profile(
        &profile_path,
        &profile_sha256,
        &candidate_lock_path,
        service,
    )?;
    let state_path = PathBuf::from(
        state_path
            .ok_or_else(|| OrchestratorError::new("service state destination is required"))?,
    );
    let launcher = PathBuf::from(
        launcher.ok_or_else(|| OrchestratorError::new("provider launcher is required"))?,
    );
    let mut bound_launcher_arguments = vec![
        OsString::from("--profile"),
        profile_path.into_os_string(),
        OsString::from("--profile-sha256"),
        OsString::from(&profile_sha256),
        OsString::from("--candidate-lock"),
        candidate_lock_path.into_os_string(),
    ];
    bound_launcher_arguments.append(&mut launcher_arguments);
    SupervisedServiceConfig::new(
        identity,
        state_path,
        CommandSpec::new(launcher, bound_launcher_arguments)?,
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
