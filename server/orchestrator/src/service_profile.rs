use std::fs;
use std::path::Path;

use serde::Deserialize;
use sha2::{Digest, Sha256};

use crate::endpoint::NumericLoopbackEndpoint;
use crate::error::OrchestratorError;
use crate::lifecycle::ProviderService;

const MAX_SERVICE_PROFILE_BYTES: u64 = 1_048_576;

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct ServiceProfileIdentity {
    service: ProviderService,
    endpoint: NumericLoopbackEndpoint,
    expected_model: String,
    profile_id: String,
    profile_sha256: String,
    candidate_lock_sha256: String,
    maximum_sequences: u8,
}

impl ServiceProfileIdentity {
    pub fn new(
        service: ProviderService,
        endpoint: NumericLoopbackEndpoint,
        expected_model: String,
        profile_id: String,
        profile_sha256: String,
        candidate_lock_sha256: String,
        maximum_sequences: u8,
    ) -> Result<Self, OrchestratorError> {
        if !valid_model_identity(&expected_model) {
            return Err(OrchestratorError::new("provider model identity is invalid"));
        }
        if profile_id != service.as_str()
            || !valid_profile_id(&profile_id)
            || !is_lower_sha256(&profile_sha256)
            || !is_lower_sha256(&candidate_lock_sha256)
            || !(1..=64).contains(&maximum_sequences)
        {
            return Err(OrchestratorError::new(
                "provider service profile identity is invalid",
            ));
        }
        Ok(Self {
            service,
            endpoint,
            expected_model,
            profile_id,
            profile_sha256,
            candidate_lock_sha256,
            maximum_sequences,
        })
    }

    pub(crate) fn service(&self) -> ProviderService {
        self.service
    }

    pub(crate) fn endpoint(&self) -> NumericLoopbackEndpoint {
        self.endpoint
    }

    pub(crate) fn expected_model(&self) -> &str {
        &self.expected_model
    }

    pub(crate) fn profile_id(&self) -> &str {
        &self.profile_id
    }

    pub(crate) fn profile_sha256(&self) -> &str {
        &self.profile_sha256
    }

    pub(crate) fn candidate_lock_sha256(&self) -> &str {
        &self.candidate_lock_sha256
    }

    pub(crate) fn maximum_sequences(&self) -> u8 {
        self.maximum_sequences
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ServiceProfileDocument {
    schema_version: u8,
    profile_id: String,
    service: ProviderService,
    endpoint: String,
    candidate_lock_sha256: String,
    expected_model: String,
    maximum_sequences: u8,
}

pub(crate) fn load_service_profile(
    profile_path: &Path,
    expected_profile_sha256: &str,
    candidate_lock_path: &Path,
    expected_service: ProviderService,
) -> Result<ServiceProfileIdentity, OrchestratorError> {
    if !is_lower_sha256(expected_profile_sha256) {
        return Err(OrchestratorError::new(
            "provider service profile digest is invalid",
        ));
    }
    let profile_bytes = read_canonical_regular_file(profile_path, "provider service profile")?;
    if hex_sha256(&profile_bytes) != expected_profile_sha256 {
        return Err(OrchestratorError::new(
            "provider service profile bytes differ",
        ));
    }
    let document: ServiceProfileDocument = serde_json::from_slice(&profile_bytes)
        .map_err(|_| OrchestratorError::new("provider service profile is invalid"))?;
    if document.schema_version != 1
        || document.service != expected_service
        || document.profile_id != expected_service.as_str()
        || !valid_profile_id(&document.profile_id)
        || !valid_model_identity(&document.expected_model)
        || !is_lower_sha256(&document.candidate_lock_sha256)
        || !(1..=64).contains(&document.maximum_sequences)
    {
        return Err(OrchestratorError::new(
            "provider service profile identity differs",
        ));
    }
    let candidate_lock_bytes =
        read_canonical_regular_file(candidate_lock_path, "agent candidate lock")?;
    if hex_sha256(&candidate_lock_bytes) != document.candidate_lock_sha256 {
        return Err(OrchestratorError::new("agent candidate lock bytes differ"));
    }
    ServiceProfileIdentity::new(
        expected_service,
        NumericLoopbackEndpoint::parse(&document.endpoint)?,
        document.expected_model,
        document.profile_id,
        expected_profile_sha256.to_owned(),
        document.candidate_lock_sha256,
        document.maximum_sequences,
    )
}

fn read_canonical_regular_file(path: &Path, component: &str) -> Result<Vec<u8>, OrchestratorError> {
    if !path.is_absolute() {
        return Err(OrchestratorError::new(format!(
            "{component} path must be absolute",
        )));
    }
    let canonical = path
        .canonicalize()
        .map_err(|_| OrchestratorError::new(format!("{component} must exist")))?;
    if canonical != path {
        return Err(OrchestratorError::new(format!(
            "{component} path must be canonical",
        )));
    }
    for ancestor in path.ancestors() {
        let metadata = fs::symlink_metadata(ancestor).map_err(|_| {
            OrchestratorError::new(format!("{component} ancestry must already exist"))
        })?;
        if metadata.file_type().is_symlink() {
            return Err(OrchestratorError::new(format!(
                "{component} ancestry must not contain symbolic links",
            )));
        }
    }
    let metadata = fs::symlink_metadata(path)
        .map_err(|_| OrchestratorError::new(format!("{component} must exist")))?;
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err(OrchestratorError::new(format!(
            "{component} must be a regular file",
        )));
    }
    if metadata.len() == 0 || metadata.len() > MAX_SERVICE_PROFILE_BYTES {
        return Err(OrchestratorError::new(format!(
            "{component} size is invalid",
        )));
    }
    fs::read(path).map_err(OrchestratorError::from)
}

fn hex_sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn is_lower_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|value| value.is_ascii_digit() || (b'a'..=b'f').contains(&value))
}

fn valid_profile_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value.bytes().enumerate().all(|(index, value)| {
            value.is_ascii_lowercase()
                || value.is_ascii_digit()
                || (index > 0 && matches!(value, b'-' | b'.'))
        })
}

fn valid_model_identity(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value.trim() == value
        && !value.chars().any(char::is_control)
}
