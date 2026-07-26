use crate::language::valid_bcp47;

use super::{
    ClientStageAttemptRecord, ClientStageName, ClientStageState, JobLedger, JobLedgerError,
    RecordingLanguageReview, RecordingLanguageReviewKind,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum LanguagePreflightOutcome {
    NotStarted,
    Running {
        attempt: u64,
    },
    RetryableFailure {
        attempt: u64,
        reason: String,
    },
    Review {
        attempt: u64,
        review: RecordingLanguageReview,
        policy_revision: String,
    },
}

impl LanguagePreflightOutcome {
    pub(crate) fn review(&self) -> Option<&RecordingLanguageReview> {
        match self {
            Self::Review { review, .. } => Some(review),
            _ => None,
        }
    }

    pub(crate) fn attempt(&self) -> u64 {
        match self {
            Self::NotStarted => 0,
            Self::Running { attempt }
            | Self::RetryableFailure { attempt, .. }
            | Self::Review { attempt, .. } => *attempt,
        }
    }
}

pub(crate) fn language_preflight_outcome(
    ledger: &JobLedger,
    job_id: &str,
) -> Result<LanguagePreflightOutcome, JobLedgerError> {
    let latest = ledger
        .list_client_stage_attempts(job_id)?
        .into_iter()
        .filter(|attempt| attempt.stage == ClientStageName::LidPreflight)
        .max_by_key(|attempt| attempt.attempt);
    let Some(latest) = latest else {
        return Ok(LanguagePreflightOutcome::NotStarted);
    };
    project_attempt(latest)
}

fn project_attempt(
    attempt: ClientStageAttemptRecord,
) -> Result<LanguagePreflightOutcome, JobLedgerError> {
    match attempt.state {
        ClientStageState::Running => Ok(LanguagePreflightOutcome::Running {
            attempt: attempt.attempt,
        }),
        ClientStageState::Succeeded => project_success(attempt),
        ClientStageState::Unavailable => project_local_manual(attempt),
        ClientStageState::Failed if attempt.retryable == Some(true) => {
            Ok(LanguagePreflightOutcome::RetryableFailure {
                attempt: attempt.attempt,
                reason: attempt.reason.ok_or(JobLedgerError::InvalidRecord(
                    "retryable LID failure has no bounded reason",
                ))?,
            })
        }
        ClientStageState::Failed | ClientStageState::Cancelled => project_terminal_failure(attempt),
    }
}

fn project_success(
    attempt: ClientStageAttemptRecord,
) -> Result<LanguagePreflightOutcome, JobLedgerError> {
    let evidence = attempt
        .evidence
        .as_ref()
        .ok_or(JobLedgerError::InvalidRecord(
            "successful LID stage has no evidence",
        ))?;
    if evidence
        .get("schemaVersion")
        .and_then(serde_json::Value::as_u64)
        != Some(1)
        || evidence
            .get("userConfirmationRequired")
            .and_then(serde_json::Value::as_bool)
            != Some(true)
    {
        return Err(JobLedgerError::InvalidRecord(
            "successful LID evidence is incompatible",
        ));
    }
    let reason = bounded_reason(evidence.get("reason"))?;
    let catalog_revision = catalog_revision(evidence.get("catalogRevision"))?;
    let policy_revision = bounded_policy_revision(
        evidence
            .get("component")
            .and_then(|component| component.get("policyRevision")),
    )?;
    let status = evidence
        .get("status")
        .and_then(serde_json::Value::as_str)
        .ok_or(JobLedgerError::InvalidRecord(
            "successful LID evidence has no status",
        ))?;
    let suggested = evidence
        .get("suggestedLocale")
        .and_then(serde_json::Value::as_str)
        .map(str::to_owned);
    let (kind, suggested_language_bcp47) = match (status, suggested) {
        ("suggestion", Some(locale)) if valid_bcp47(&locale) => {
            (RecordingLanguageReviewKind::Suggestion, Some(locale))
        }
        ("manual", None) => (RecordingLanguageReviewKind::Manual, None),
        _ => {
            return Err(JobLedgerError::InvalidRecord(
                "successful LID evidence has an invalid suggestion",
            ))
        }
    };
    Ok(LanguagePreflightOutcome::Review {
        attempt: attempt.attempt,
        review: RecordingLanguageReview {
            kind,
            suggested_language_bcp47,
            reason,
            catalog_revision,
        },
        policy_revision,
    })
}

fn project_local_manual(
    attempt: ClientStageAttemptRecord,
) -> Result<LanguagePreflightOutcome, JobLedgerError> {
    let evidence = attempt
        .evidence
        .as_ref()
        .ok_or(JobLedgerError::InvalidRecord(
            "manual LID stage has no evidence",
        ))?;
    if evidence
        .get("schemaVersion")
        .and_then(serde_json::Value::as_u64)
        != Some(1)
        || evidence.get("outcome").and_then(serde_json::Value::as_str) != Some("manual")
    {
        return Err(JobLedgerError::InvalidRecord(
            "manual LID evidence is incompatible",
        ));
    }
    let reason = bounded_reason(evidence.get("reason"))?;
    Ok(LanguagePreflightOutcome::Review {
        attempt: attempt.attempt,
        review: RecordingLanguageReview {
            kind: RecordingLanguageReviewKind::Manual,
            suggested_language_bcp47: None,
            reason,
            catalog_revision: catalog_revision(evidence.get("catalogRevision"))?,
        },
        policy_revision: bounded_policy_revision(evidence.get("policyRevision"))?,
    })
}

fn project_terminal_failure(
    attempt: ClientStageAttemptRecord,
) -> Result<LanguagePreflightOutcome, JobLedgerError> {
    let evidence = attempt
        .evidence
        .as_ref()
        .ok_or(JobLedgerError::InvalidRecord(
            "terminal LID failure has no evidence",
        ))?;
    if evidence
        .get("schemaVersion")
        .and_then(serde_json::Value::as_u64)
        != Some(1)
        || evidence.get("outcome").and_then(serde_json::Value::as_str) != Some("failed")
    {
        return Err(JobLedgerError::InvalidRecord(
            "terminal LID failure evidence is incompatible",
        ));
    }
    let reason = bounded_reason(evidence.get("reason"))?;
    Ok(LanguagePreflightOutcome::Review {
        attempt: attempt.attempt,
        review: RecordingLanguageReview {
            kind: RecordingLanguageReviewKind::Manual,
            suggested_language_bcp47: None,
            reason,
            catalog_revision: catalog_revision(evidence.get("catalogRevision"))?,
        },
        policy_revision: bounded_policy_revision(evidence.get("policyRevision"))?,
    })
}

fn bounded_reason(value: Option<&serde_json::Value>) -> Result<String, JobLedgerError> {
    bounded_text(value, 64, "LID review reason")
}

fn bounded_policy_revision(value: Option<&serde_json::Value>) -> Result<String, JobLedgerError> {
    bounded_text(value, 128, "LID policy revision")
}

fn bounded_text(
    value: Option<&serde_json::Value>,
    maximum_bytes: usize,
    field: &'static str,
) -> Result<String, JobLedgerError> {
    let value = value
        .and_then(serde_json::Value::as_str)
        .ok_or(JobLedgerError::InvalidRecord(field))?;
    if value.is_empty()
        || value.len() > maximum_bytes
        || value
            .chars()
            .any(|character| character.is_control() || character.is_whitespace())
    {
        return Err(JobLedgerError::InvalidRecord(field));
    }
    Ok(value.to_owned())
}

fn catalog_revision(value: Option<&serde_json::Value>) -> Result<String, JobLedgerError> {
    let revision =
        value
            .and_then(serde_json::Value::as_str)
            .ok_or(JobLedgerError::InvalidRecord(
                "LID catalog revision is missing",
            ))?;
    if revision.len() != 64
        || !revision
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(JobLedgerError::InvalidRecord(
            "LID catalog revision is invalid",
        ));
    }
    Ok(revision.to_owned())
}
