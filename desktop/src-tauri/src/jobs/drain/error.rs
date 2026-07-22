use crate::{
    jobs::{AsrCatalogBinding, REMOTE_STAGE_RETRY_REQUESTED},
    server_connector::{
        batch::{ApiError, BatchClientError},
        AsrCatalogDispatchProof, BatchConnectionLease, ServerConnector,
    },
};

const MAX_AUTOMATIC_REMOTE_ATTEMPTS: u64 = 6;
const DURABLE_CAPACITY_RETRY_DELAY_MS: u64 = 30_000;
const DURABLE_AMBIGUOUS_COMMIT_RETRY_DELAY_MS: u64 = 5_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum RetryDisposition {
    Terminal,
    BoundedTransport,
    DurableCapacity,
    DurableAmbiguousCommit,
}

#[derive(Debug)]
pub(super) struct DrainStepError {
    pub(super) detail: String,
    pub(super) retry_disposition: RetryDisposition,
    pub(super) code: &'static str,
    pub(super) user_message: &'static str,
}

impl DrainStepError {
    pub(super) fn permanent(detail: impl Into<String>) -> Self {
        Self {
            detail: detail.into(),
            retry_disposition: RetryDisposition::Terminal,
            code: "REMOTE_STATE_INVALID",
            user_message: "The private-server job state is incompatible. Retry the recording to start a new server job.",
        }
    }

    pub(super) fn transient_state(detail: impl Into<String>) -> Self {
        Self {
            detail: detail.into(),
            retry_disposition: RetryDisposition::BoundedTransport,
            code: "REMOTE_REQUEST_RETRYING",
            user_message:
                "The private-server request did not complete. Yap will retry automatically.",
        }
    }

    pub(super) fn catalog_revalidation(detail: impl Into<String>) -> Self {
        Self {
            detail: detail.into(),
            retry_disposition: RetryDisposition::Terminal,
            code: "ASR_CAPABILITY_UNAVAILABLE",
            user_message: "The current private server must revalidate this recording language before dispatch.",
        }
    }

    pub(super) fn requires_catalog_revalidation(&self) -> bool {
        self.code == "ASR_CAPABILITY_UNAVAILABLE"
    }

    fn durable_capacity(detail: impl Into<String>) -> Self {
        Self {
            detail: detail.into(),
            retry_disposition: RetryDisposition::DurableCapacity,
            code: "REMOTE_CAPACITY_WAITING",
            user_message:
                "The private server is busy. Yap will retry this recording automatically.",
        }
    }

    pub(super) fn durable_ambiguous_commit(detail: impl Into<String>) -> Self {
        Self {
            detail: detail.into(),
            retry_disposition: RetryDisposition::DurableAmbiguousCommit,
            code: "REMOTE_COMMIT_RECONCILING",
            user_message: "Yap is confirming whether the private server accepted this recording and will retry automatically.",
        }
    }

    pub(super) fn stage_retry_reconciling(detail: impl Into<String>) -> Self {
        Self {
            detail: detail.into(),
            retry_disposition: RetryDisposition::DurableAmbiguousCommit,
            code: REMOTE_STAGE_RETRY_REQUESTED,
            user_message: "Yap is confirming the failed ASR-stage retry against the existing uploaded recording.",
        }
    }

    pub(super) fn from_stage_query_error(error: BatchClientError) -> Self {
        let retryable = error.is_retryable();
        let detail = error.to_string();
        if retryable {
            Self::stage_retry_reconciling(detail)
        } else {
            Self::permanent(detail)
        }
    }

    pub(super) fn from_stage_retry_commit_error(error: BatchClientError) -> Self {
        let ambiguous = matches!(
            &error,
            BatchClientError::Transport(_)
                | BatchClientError::ResponseTooLarge
                | BatchClientError::MalformedResponse
                | BatchClientError::Api {
                    retryable: true,
                    ..
                }
        );
        let detail = error.to_string();
        if ambiguous {
            Self::stage_retry_reconciling(detail)
        } else {
            Self::permanent(detail)
        }
    }

    pub(super) fn from_commit_error(error: BatchClientError) -> Self {
        let is_capacity = matches!(
            &error,
            BatchClientError::Api { code, .. } if code == "SERVER_BUSY"
        );
        let is_legacy_commit_in_flight = matches!(
            &error,
            BatchClientError::Api { code, .. } if code == "JOB_NOT_COMMITTABLE"
        );
        let is_ambiguous = matches!(
            &error,
            BatchClientError::Transport(_)
                | BatchClientError::ResponseTooLarge
                | BatchClientError::MalformedResponse
                | BatchClientError::Api {
                    retryable: true,
                    ..
                }
        );
        let detail = error.to_string();
        if is_capacity {
            Self::durable_capacity(detail)
        } else if is_legacy_commit_in_flight || is_ambiguous {
            Self::durable_ambiguous_commit(detail)
        } else {
            Self::permanent(detail)
        }
    }

    pub(super) fn durable_retry_at(&self, updated_at_ms: u64) -> Option<u64> {
        let delay_ms = match self.retry_disposition {
            RetryDisposition::DurableCapacity => DURABLE_CAPACITY_RETRY_DELAY_MS,
            RetryDisposition::DurableAmbiguousCommit => DURABLE_AMBIGUOUS_COMMIT_RETRY_DELAY_MS,
            RetryDisposition::Terminal | RetryDisposition::BoundedTransport => return None,
        };
        Some(updated_at_ms.saturating_add(delay_ms))
    }

    pub(super) fn terminal_server(error: &ApiError) -> Self {
        Self {
            detail: format!(
                "server job failed with {} (request {}, retryable={})",
                error.code, error.request_id, error.retryable
            ),
            retry_disposition: RetryDisposition::Terminal,
            code: "REMOTE_SERVER_FAILED",
            user_message: "The private server could not complete this recording. Retry it to start a new server job.",
        }
    }
}

impl std::fmt::Display for DrainStepError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.detail)
    }
}

impl From<String> for DrainStepError {
    fn from(detail: String) -> Self {
        Self::permanent(detail)
    }
}

impl From<&str> for DrainStepError {
    fn from(detail: &str) -> Self {
        Self::permanent(detail)
    }
}

impl From<BatchClientError> for DrainStepError {
    fn from(error: BatchClientError) -> Self {
        let is_capacity = matches!(
            &error,
            BatchClientError::Api { code, .. } if code == "SERVER_BUSY"
        );
        let is_retryable = error.is_retryable();
        let detail = error.to_string();
        if is_capacity {
            Self::durable_capacity(detail)
        } else if is_retryable {
            Self::transient_state(detail)
        } else {
            Self::permanent(detail)
        }
    }
}

pub(super) type DrainResult<T> = Result<T, DrainStepError>;

pub(super) enum BatchCommitGuard<'a> {
    PersistedCleanup,
    #[cfg(test)]
    Unchecked,
    #[cfg(test)]
    StaleForTest,
    #[cfg(test)]
    StaleAfterForTest {
        remaining_successes: &'a std::sync::atomic::AtomicUsize,
    },
    Lease {
        connector: &'a ServerConnector,
        lease: &'a BatchConnectionLease,
    },
    Catalog {
        connector: &'a ServerConnector,
        lease: &'a BatchConnectionLease,
        proof: &'a AsrCatalogDispatchProof,
    },
}

impl BatchCommitGuard<'_> {
    pub(super) fn commit<T>(&self, mutation: impl FnOnce() -> DrainResult<T>) -> DrainResult<T> {
        match self {
            Self::PersistedCleanup => mutation(),
            #[cfg(test)]
            Self::Unchecked => mutation(),
            #[cfg(test)]
            Self::StaleForTest => Err(DrainStepError::transient_state("test stale lease")),
            #[cfg(test)]
            Self::StaleAfterForTest {
                remaining_successes,
            } => {
                let remaining = remaining_successes.load(std::sync::atomic::Ordering::SeqCst);
                if remaining == 0 {
                    Err(DrainStepError::transient_state("test stale lease"))
                } else {
                    remaining_successes.fetch_sub(1, std::sync::atomic::Ordering::SeqCst);
                    mutation()
                }
            }
            Self::Lease { connector, lease } => connector
                .with_current_batch_lease(lease, mutation)
                .map_err(DrainStepError::transient_state)?,
            Self::Catalog {
                connector, lease, ..
            } => connector
                .with_current_batch_lease(lease, mutation)
                .map_err(DrainStepError::transient_state)?,
        }
    }

    pub(super) fn commit_catalog<T>(
        &self,
        binding: &AsrCatalogBinding,
        mutation: impl FnOnce() -> DrainResult<T>,
    ) -> DrainResult<T> {
        match self {
            Self::Catalog {
                connector,
                lease,
                proof,
            } => connector
                .with_current_batch_catalog_proof(lease, proof, binding, mutation)
                .map_err(DrainStepError::catalog_revalidation)?,
            #[cfg(test)]
            Self::Unchecked | Self::StaleForTest | Self::StaleAfterForTest { .. } => {
                self.commit(mutation)
            }
            Self::PersistedCleanup | Self::Lease { .. } => {
                Err(DrainStepError::catalog_revalidation(
                    "A live current ASR catalog proof is required before remote job creation.",
                ))
            }
        }
    }

    pub(super) fn ensure_current(&self) -> DrainResult<()> {
        self.commit(|| Ok(()))
    }
}

pub(super) fn remote_retry_plan(
    error: &DrainStepError,
    attempt_count: u64,
    updated_at_ms: u64,
) -> (Option<u64>, &'static str, &'static str) {
    if let Some(retry_at_ms) = error.durable_retry_at(updated_at_ms) {
        return (Some(retry_at_ms), error.code, error.user_message);
    }
    let delay_seconds =
        [1_u64, 2, 4, 8, 15, 30][usize::try_from(attempt_count).unwrap_or(usize::MAX).min(5)];
    let bounded_retry = error.retry_disposition == RetryDisposition::BoundedTransport;
    let retry_at_ms = (bounded_retry && attempt_count < MAX_AUTOMATIC_REMOTE_ATTEMPTS)
        .then(|| updated_at_ms.saturating_add(delay_seconds.saturating_mul(1_000)));
    if bounded_retry && retry_at_ms.is_none() {
        return (
            None,
            "REMOTE_RETRY_EXHAUSTED",
            "The private-server request did not recover after bounded retries. Retry the recording to start a new server job.",
        );
    }
    (retry_at_ms, error.code, error.user_message)
}
