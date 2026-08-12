use std::time::Duration;

use serde::Serialize;

use crate::agent_work::{is_lower_sha256, AgentWorkRequest, ExecutionRoute};
use crate::error::OrchestratorError;
use crate::lifecycle::ProviderService;

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct ProviderRouteIdentity {
    pub(super) service: ProviderService,
    pub(super) profile_sha256: String,
    pub(super) candidate_lock_sha256: String,
}

impl ProviderRouteIdentity {
    pub fn new(
        service: ProviderService,
        profile_sha256: String,
        candidate_lock_sha256: String,
    ) -> Result<Self, OrchestratorError> {
        if !is_lower_sha256(&profile_sha256) || !is_lower_sha256(&candidate_lock_sha256) {
            return Err(OrchestratorError::new(
                "provider admission identity is invalid",
            ));
        }
        Ok(Self {
            service,
            profile_sha256,
            candidate_lock_sha256,
        })
    }
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct AdmissionLease {
    pub(super) request: AgentWorkRequest,
    pub(super) submitted_at: Duration,
    pub(super) admitted_at: Duration,
    pub(super) provider_generation: Option<u64>,
}

impl AdmissionLease {
    pub fn request_id(&self) -> &str {
        self.request.request_id()
    }

    pub fn request(&self) -> &AgentWorkRequest {
        &self.request
    }

    pub fn admitted_at(&self) -> Duration {
        self.admitted_at
    }

    pub fn queue_duration(&self) -> Duration {
        self.admitted_at.saturating_sub(self.submitted_at)
    }

    pub fn provider_generation(&self) -> Option<u64> {
        self.provider_generation
    }
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum AdmissionDecision {
    Queued,
    ProviderUnavailable(ExecutionRoute),
    DeadlineExceeded,
    DuplicateRequest,
    NotFoundOrUnauthorized,
    OwnerQueueFull,
    QueueFull,
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum AdmissionEvent {
    Admitted(AdmissionLease),
    DeadlineExceeded {
        request_id: String,
    },
    ProviderUnavailable {
        request_id: String,
        route: ExecutionRoute,
    },
    ActiveCancellationRequested {
        request_id: String,
        reason: CancellationReason,
    },
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum CancellationReason {
    ClientRequested,
    DeadlineExceeded,
    ProviderUnavailable,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum CancellationDecision {
    QueuedCancelled,
    ActiveCancellationRequested,
    AlreadyCancellationRequested,
    NotFoundOrUnauthorized,
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum AdmissionStatus {
    Queued,
    Admitted(AdmissionLease),
    ActiveCancellationRequested(CancellationReason),
    Terminal(TerminalOutcome),
    NotFoundOrUnauthorized,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum TerminalOutcome {
    Completed,
    Cancelled,
    DeadlineExceeded,
    ProviderUnavailable(ExecutionRoute),
}
