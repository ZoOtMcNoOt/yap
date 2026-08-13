mod dispatch;
mod owner_queue;
mod priority;
mod terminal;
mod types;

pub use types::{
    AdmissionDecision, AdmissionEvent, AdmissionLease, AdmissionStatus, CancellationDecision,
    CancellationReason, ProviderRouteIdentity, TerminalOutcome,
};

use std::collections::{BTreeMap, HashMap, VecDeque};
use std::time::Duration;

use owner_queue::OwnerFairQueue;
use terminal::TerminalWork;

use crate::agent_work::{AgentWorkRequest, ExecutionRoute, SchedulingClass};
use crate::error::OrchestratorError;
use crate::lifecycle::{LifecycleState, ProviderService, ServiceSnapshot};

const MAXIMUM_PENDING_REQUESTS: usize = 64;
const MAXIMUM_PENDING_REQUESTS_PER_OWNER: usize = 4;

#[derive(Debug)]
struct ActiveWork {
    lease: AdmissionLease,
    cancellation_reason: Option<CancellationReason>,
}

#[derive(Debug)]
struct PendingWork {
    request: AgentWorkRequest,
    submitted_at: Duration,
}

#[derive(Debug)]
pub struct AgentAdmissionScheduler {
    expected_routes: BTreeMap<ExecutionRoute, ProviderRouteIdentity>,
    observed_provider_generations: BTreeMap<ExecutionRoute, u64>,
    provider_generations: BTreeMap<ExecutionRoute, u64>,
    pending: HashMap<String, PendingWork>,
    queues: BTreeMap<(ExecutionRoute, SchedulingClass), OwnerFairQueue>,
    active: HashMap<String, ActiveWork>,
    terminal: HashMap<String, TerminalWork>,
    terminal_order: VecDeque<String>,
    priority_cursors: BTreeMap<ExecutionRoute, usize>,
    deferred_events: VecDeque<AdmissionEvent>,
}

impl AgentAdmissionScheduler {
    pub fn new(
        rapid: ProviderRouteIdentity,
        complex: ProviderRouteIdentity,
    ) -> Result<Self, OrchestratorError> {
        if rapid.service != ProviderService::RapidAutomation
            || complex.service != ProviderService::ComplexOrchestration
            || rapid.active_capacity != 4
            || complex.active_capacity != 8
            || rapid.profile_sha256 == complex.profile_sha256
            || rapid.candidate_lock_sha256 != complex.candidate_lock_sha256
        {
            return Err(OrchestratorError::new(
                "provider admission routes differ from the exact two-route policy",
            ));
        }
        Ok(Self {
            expected_routes: BTreeMap::from([
                (ExecutionRoute::RapidAutomation, rapid),
                (ExecutionRoute::ComplexOrchestration, complex),
            ]),
            observed_provider_generations: BTreeMap::new(),
            provider_generations: BTreeMap::new(),
            pending: HashMap::new(),
            queues: BTreeMap::new(),
            active: HashMap::new(),
            terminal: HashMap::new(),
            terminal_order: VecDeque::new(),
            priority_cursors: BTreeMap::new(),
            deferred_events: VecDeque::new(),
        })
    }

    pub fn observe_provider(
        &mut self,
        snapshot: &ServiceSnapshot,
    ) -> Result<Vec<AdmissionEvent>, OrchestratorError> {
        let route = ExecutionRoute::from_provider(snapshot.service);
        let expected = self
            .expected_routes
            .get(&route)
            .expect("both provider routes are initialized");
        if snapshot.schema_version != 2
            || snapshot.profile_id != snapshot.service.as_str()
            || snapshot.profile_sha256 != expected.profile_sha256
            || snapshot.candidate_lock_sha256 != expected.candidate_lock_sha256
            || (snapshot.state == LifecycleState::Ready && snapshot.process_generation == 0)
        {
            self.provider_generations.remove(&route);
            let events = self.disrupt_route(route);
            self.deferred_events.extend(events);
            return Err(OrchestratorError::new(
                "provider admission snapshot differs from its exact route identity",
            ));
        }

        let previous_observed_generation = self.observed_provider_generations.get(&route).copied();
        if previous_observed_generation
            .is_some_and(|previous| snapshot.process_generation < previous)
        {
            self.provider_generations.remove(&route);
            let events = self.disrupt_route(route);
            self.deferred_events.extend(events);
            return Err(OrchestratorError::new(
                "provider admission generation moved backwards",
            ));
        }
        self.observed_provider_generations
            .insert(route, snapshot.process_generation);

        let next_ready_generation =
            (snapshot.state == LifecycleState::Ready).then_some(snapshot.process_generation);
        let previous_ready_generation = self.provider_generations.get(&route).copied();
        let events = if previous_ready_generation.is_some()
            && previous_ready_generation != next_ready_generation
        {
            self.disrupt_route(route)
        } else {
            Vec::new()
        };
        match next_ready_generation {
            Some(generation) => {
                self.provider_generations.insert(route, generation);
            }
            None => {
                self.provider_generations.remove(&route);
            }
        }
        Ok(events)
    }

    pub fn mark_provider_unavailable(
        &mut self,
        route: ExecutionRoute,
    ) -> Result<Vec<AdmissionEvent>, OrchestratorError> {
        if route == ExecutionRoute::ServerIo {
            return Err(OrchestratorError::new(
                "server IO is not a model provider route",
            ));
        }
        self.provider_generations.remove(&route);
        Ok(self.disrupt_route(route))
    }

    pub fn submit(
        &mut self,
        request: AgentWorkRequest,
        observed_at: Duration,
    ) -> AdmissionDecision {
        if request.deadline_at() <= observed_at {
            return AdmissionDecision::DeadlineExceeded;
        }
        if let Some(existing_token) = self.request_token(request.request_id()) {
            return if existing_token == request.cancellation_token() {
                AdmissionDecision::DuplicateRequest
            } else {
                AdmissionDecision::NotFoundOrUnauthorized
            };
        }
        if request.route() != ExecutionRoute::ServerIo
            && !self.provider_generations.contains_key(&request.route())
        {
            return AdmissionDecision::ProviderUnavailable(request.route());
        }
        if self.pending.len() >= MAXIMUM_PENDING_REQUESTS {
            return AdmissionDecision::QueueFull;
        }
        if self
            .pending
            .values()
            .filter(|queued| queued.request.owner() == request.owner())
            .count()
            + self
                .active
                .values()
                .filter(|active| active.lease.request.owner() == request.owner())
                .count()
            >= MAXIMUM_PENDING_REQUESTS_PER_OWNER
        {
            return AdmissionDecision::OwnerQueueFull;
        }
        self.queues
            .entry((request.route(), request.scheduling_class()))
            .or_default()
            .push(&request);
        self.pending.insert(
            request.request_id().to_owned(),
            PendingWork {
                request,
                submitted_at: observed_at,
            },
        );
        AdmissionDecision::Queued
    }

    pub fn dispatch(&mut self, observed_at: Duration) -> Vec<AdmissionEvent> {
        let mut events = self.deferred_events.drain(..).collect::<Vec<_>>();
        events.extend(self.expire(observed_at));
        for route in [
            ExecutionRoute::ServerIo,
            ExecutionRoute::RapidAutomation,
            ExecutionRoute::ComplexOrchestration,
        ] {
            self.dispatch_non_idle(route, observed_at, &mut events);
        }
        if self.non_idle_work_is_absent() {
            self.dispatch_idle(observed_at, &mut events);
        }
        events
    }

    pub(super) fn active_capacity(&self, route: ExecutionRoute) -> usize {
        match route {
            ExecutionRoute::ServerIo => 1,
            ExecutionRoute::RapidAutomation | ExecutionRoute::ComplexOrchestration => {
                self.expected_routes
                    .get(&route)
                    .expect("both model routes are initialized")
                    .active_capacity
            }
        }
    }

    pub fn cancel(&mut self, request_id: &str, token: &str) -> CancellationDecision {
        if let Some(pending) = self.pending.get(request_id) {
            if pending.request.cancellation_token() != token {
                return CancellationDecision::NotFoundOrUnauthorized;
            }
            let request = pending.request.clone();
            self.remove_pending(&request);
            self.record_terminal(&request, TerminalOutcome::Cancelled);
            return CancellationDecision::QueuedCancelled;
        }
        let Some(active) = self.active.get_mut(request_id) else {
            return CancellationDecision::NotFoundOrUnauthorized;
        };
        if active.lease.request.cancellation_token() != token {
            return CancellationDecision::NotFoundOrUnauthorized;
        }
        if active.cancellation_reason.is_some() {
            return CancellationDecision::AlreadyCancellationRequested;
        }
        active.cancellation_reason = Some(CancellationReason::ClientRequested);
        CancellationDecision::ActiveCancellationRequested
    }

    pub fn status(&self, request_id: &str, token: &str) -> AdmissionStatus {
        if let Some(pending) = self.pending.get(request_id) {
            return if pending.request.cancellation_token() == token {
                AdmissionStatus::Queued
            } else {
                AdmissionStatus::NotFoundOrUnauthorized
            };
        }
        if let Some(active) = self.active.get(request_id) {
            if active.lease.request.cancellation_token() != token {
                return AdmissionStatus::NotFoundOrUnauthorized;
            }
            return match active.cancellation_reason {
                Some(reason) => AdmissionStatus::ActiveCancellationRequested(reason),
                None => AdmissionStatus::Admitted(active.lease.clone()),
            };
        }
        match self.terminal.get(request_id) {
            Some(terminal) if terminal.cancellation_token == token => {
                AdmissionStatus::Terminal(terminal.outcome)
            }
            _ => AdmissionStatus::NotFoundOrUnauthorized,
        }
    }

    pub fn acknowledge_cancellation(
        &mut self,
        request_id: &str,
        token: &str,
    ) -> Result<(), OrchestratorError> {
        if self.terminal_status_matches(request_id, token, |outcome| {
            !matches!(outcome, TerminalOutcome::Completed)
        }) {
            return Ok(());
        }
        let active = self.active.get(request_id);
        if active.is_none_or(|active| {
            active.lease.request.cancellation_token() != token
                || active.cancellation_reason.is_none()
        }) {
            return Err(OrchestratorError::new(
                "active agent cancellation is unavailable",
            ));
        }
        let active = self
            .active
            .remove(request_id)
            .expect("active cancellation was checked");
        let outcome = match active
            .cancellation_reason
            .expect("active cancellation reason was checked")
        {
            CancellationReason::ClientRequested => TerminalOutcome::Cancelled,
            CancellationReason::DeadlineExceeded => TerminalOutcome::DeadlineExceeded,
            CancellationReason::ProviderUnavailable => {
                TerminalOutcome::ProviderUnavailable(active.lease.request.route())
            }
        };
        self.record_terminal(&active.lease.request, outcome);
        Ok(())
    }

    pub fn complete(&mut self, request_id: &str, token: &str) -> Result<(), OrchestratorError> {
        if self.terminal_status_matches(request_id, token, |outcome| {
            outcome == TerminalOutcome::Completed
        }) {
            return Ok(());
        }
        let active = self.active.get(request_id);
        if active.is_none_or(|active| active.lease.request.cancellation_token() != token) {
            return Err(OrchestratorError::new(
                "active agent completion is unavailable",
            ));
        }
        let active = active.expect("active completion was checked");
        if active.cancellation_reason.is_some() {
            return Err(OrchestratorError::new(
                "cancelled agent work must acknowledge cancellation",
            ));
        }
        let active = self
            .active
            .remove(request_id)
            .expect("active completion was checked");
        self.record_terminal(&active.lease.request, TerminalOutcome::Completed);
        Ok(())
    }

    pub fn active_count(&self) -> usize {
        self.active.len()
    }

    fn request_token(&self, request_id: &str) -> Option<&str> {
        self.pending
            .get(request_id)
            .map(|pending| pending.request.cancellation_token())
            .or_else(|| {
                self.active
                    .get(request_id)
                    .map(|active| active.lease.request.cancellation_token())
            })
            .or_else(|| {
                self.terminal
                    .get(request_id)
                    .map(|terminal| terminal.cancellation_token.as_str())
            })
    }
}
