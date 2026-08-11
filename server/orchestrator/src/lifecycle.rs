use std::collections::VecDeque;
use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::error::OrchestratorError;

const SNAPSHOT_SCHEMA_VERSION: u8 = 1;
const MAXIMUM_RESTARTS_PER_WINDOW: usize = 3;
const RESTART_WINDOW: Duration = Duration::from_secs(60);
const RESTART_BACKOFFS: [Duration; MAXIMUM_RESTARTS_PER_WINDOW] = [
    Duration::from_secs(1),
    Duration::from_secs(2),
    Duration::from_secs(4),
];

#[derive(Debug, Clone, Copy, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum ProviderService {
    RapidAutomation,
    ComplexOrchestration,
}

impl ProviderService {
    pub fn parse(value: &str) -> Result<Self, OrchestratorError> {
        match value {
            "rapid-automation" => Ok(Self::RapidAutomation),
            "complex-orchestration" => Ok(Self::ComplexOrchestration),
            _ => Err(OrchestratorError::new(
                "provider service must be one explicit workload route",
            )),
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::RapidAutomation => "rapid-automation",
            Self::ComplexOrchestration => "complex-orchestration",
        }
    }
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum LifecycleState {
    Starting,
    Ready,
    RestartBackoff,
    Failed,
    Stopping,
    Stopped,
}

#[derive(Debug, Clone, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ServiceSnapshot {
    pub schema_version: u8,
    pub service: ProviderService,
    pub state: LifecycleState,
    pub process_generation: u64,
    pub start_count: u64,
    pub restart_count: u64,
    pub consecutive_failure_count: u64,
    pub readiness_transition_count: u64,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum RestartDecision {
    After(Duration),
    Exhausted,
}

#[derive(Debug)]
pub struct LifecycleTracker {
    snapshot: ServiceSnapshot,
    restart_observations: VecDeque<Duration>,
}

impl LifecycleTracker {
    pub fn new(service: ProviderService) -> Self {
        Self {
            snapshot: ServiceSnapshot {
                schema_version: SNAPSHOT_SCHEMA_VERSION,
                service,
                state: LifecycleState::Starting,
                process_generation: 0,
                start_count: 0,
                restart_count: 0,
                consecutive_failure_count: 0,
                readiness_transition_count: 0,
            },
            restart_observations: VecDeque::new(),
        }
    }

    pub fn snapshot(&self) -> &ServiceSnapshot {
        &self.snapshot
    }

    pub fn record_start(&mut self) -> Result<(), OrchestratorError> {
        if !matches!(
            self.snapshot.state,
            LifecycleState::Starting | LifecycleState::RestartBackoff
        ) {
            return Err(OrchestratorError::new(
                "provider service cannot start from its current state",
            ));
        }
        self.snapshot.state = LifecycleState::Starting;
        self.snapshot.process_generation = self
            .snapshot
            .process_generation
            .checked_add(1)
            .ok_or_else(|| OrchestratorError::new("process generation overflowed"))?;
        self.snapshot.start_count = self
            .snapshot
            .start_count
            .checked_add(1)
            .ok_or_else(|| OrchestratorError::new("start count overflowed"))?;
        Ok(())
    }

    pub fn record_ready(&mut self) -> Result<(), OrchestratorError> {
        if self.snapshot.state != LifecycleState::Starting || self.snapshot.process_generation == 0
        {
            return Err(OrchestratorError::new(
                "provider service readiness was observed outside startup",
            ));
        }
        self.snapshot.state = LifecycleState::Ready;
        self.snapshot.readiness_transition_count = self
            .snapshot
            .readiness_transition_count
            .checked_add(1)
            .ok_or_else(|| OrchestratorError::new("readiness count overflowed"))?;
        self.snapshot.consecutive_failure_count = 0;
        Ok(())
    }

    pub fn record_unexpected_exit(&mut self, observed_at: Duration) -> RestartDecision {
        if matches!(
            self.snapshot.state,
            LifecycleState::Failed | LifecycleState::Stopping | LifecycleState::Stopped
        ) {
            return RestartDecision::Exhausted;
        }
        while self
            .restart_observations
            .front()
            .is_some_and(|earliest| observed_at.saturating_sub(*earliest) >= RESTART_WINDOW)
        {
            self.restart_observations.pop_front();
        }
        self.snapshot.consecutive_failure_count =
            self.snapshot.consecutive_failure_count.saturating_add(1);
        if self.restart_observations.len() >= MAXIMUM_RESTARTS_PER_WINDOW {
            self.snapshot.state = LifecycleState::Failed;
            return RestartDecision::Exhausted;
        }
        let backoff = RESTART_BACKOFFS[self.restart_observations.len()];
        self.restart_observations.push_back(observed_at);
        self.snapshot.restart_count = self.snapshot.restart_count.saturating_add(1);
        self.snapshot.state = LifecycleState::RestartBackoff;
        RestartDecision::After(backoff)
    }

    pub fn record_stopping(&mut self) -> Result<(), OrchestratorError> {
        if self.snapshot.state == LifecycleState::Stopped {
            return Err(OrchestratorError::new(
                "provider service is already stopped",
            ));
        }
        self.snapshot.state = LifecycleState::Stopping;
        Ok(())
    }

    pub fn record_stopped(&mut self) -> Result<(), OrchestratorError> {
        if self.snapshot.state != LifecycleState::Stopping {
            return Err(OrchestratorError::new(
                "provider service cannot stop outside shutdown",
            ));
        }
        self.snapshot.state = LifecycleState::Stopped;
        Ok(())
    }
}
