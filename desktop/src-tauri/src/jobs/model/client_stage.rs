use super::JobLedgerError;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClientStageName {
    Normalization,
    Vad,
    LidPreflight,
    UserConfirmation,
}

impl ClientStageName {
    pub(crate) const fn as_db(self) -> &'static str {
        match self {
            Self::Normalization => "normalization",
            Self::Vad => "vad",
            Self::LidPreflight => "lid_preflight",
            Self::UserConfirmation => "user_confirmation",
        }
    }

    pub(crate) fn from_db(value: &str) -> Result<Self, JobLedgerError> {
        match value {
            "normalization" => Ok(Self::Normalization),
            "vad" => Ok(Self::Vad),
            "lid_preflight" => Ok(Self::LidPreflight),
            "user_confirmation" => Ok(Self::UserConfirmation),
            _ => Err(JobLedgerError::CorruptValue {
                field: "client_stage",
                value: value.into(),
            }),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClientStageState {
    Running,
    Succeeded,
    Unavailable,
    Failed,
    Cancelled,
}

impl ClientStageState {
    pub(crate) const fn as_db(self) -> &'static str {
        match self {
            Self::Running => "running",
            Self::Succeeded => "succeeded",
            Self::Unavailable => "unavailable",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
        }
    }

    pub(crate) fn from_db(value: &str) -> Result<Self, JobLedgerError> {
        match value {
            "running" => Ok(Self::Running),
            "succeeded" => Ok(Self::Succeeded),
            "unavailable" => Ok(Self::Unavailable),
            "failed" => Ok(Self::Failed),
            "cancelled" => Ok(Self::Cancelled),
            _ => Err(JobLedgerError::CorruptValue {
                field: "client_stage_state",
                value: value.into(),
            }),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClientStageAttemptRecord {
    pub job_id: String,
    pub stage: ClientStageName,
    pub attempt: u64,
    pub state: ClientStageState,
    pub input_fingerprint_sha256: String,
    pub output_fingerprint_sha256: Option<String>,
    pub component_id: String,
    pub component_revision: String,
    pub started_at_ms: u64,
    pub completed_at_ms: Option<u64>,
    pub retryable: Option<bool>,
    pub reason: Option<String>,
    pub evidence: Option<serde_json::Value>,
    pub evidence_sha256: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ClientStageStart {
    pub stage: ClientStageName,
    pub input_fingerprint_sha256: String,
    pub component_id: String,
    pub component_revision: String,
    pub started_at_ms: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ClientStageFinish {
    pub stage: ClientStageName,
    pub attempt: u64,
    pub state: ClientStageState,
    pub output_fingerprint_sha256: Option<String>,
    pub completed_at_ms: u64,
    pub retryable: bool,
    pub reason: Option<String>,
    pub evidence: Option<serde_json::Value>,
}
