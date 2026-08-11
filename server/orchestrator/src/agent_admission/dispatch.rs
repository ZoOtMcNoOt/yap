use std::collections::HashSet;
use std::time::Duration;

use super::priority::priority_schedule;
use super::{
    ActiveWork, AdmissionEvent, AdmissionLease, AgentAdmissionScheduler, CancellationReason,
    TerminalOutcome,
};
use crate::agent_work::{AgentWorkRequest, ExecutionRoute, SchedulingClass, WorkOwner};

const ACTIVE_CAPACITY_PER_ROUTE: usize = 1;

impl AgentAdmissionScheduler {
    pub(super) fn expire(&mut self, observed_at: Duration) -> Vec<AdmissionEvent> {
        let expired_pending = self
            .pending
            .values()
            .filter(|pending| pending.request.deadline_at() <= observed_at)
            .map(|pending| pending.request.clone())
            .collect::<Vec<_>>();
        let mut events = Vec::with_capacity(expired_pending.len());
        for request in expired_pending {
            self.remove_pending(&request);
            self.record_terminal(&request, TerminalOutcome::DeadlineExceeded);
            events.push(AdmissionEvent::DeadlineExceeded {
                request_id: request.request_id().to_owned(),
            });
        }
        for active in self.active.values_mut() {
            if active.lease.request.deadline_at() <= observed_at
                && active.cancellation_reason.is_none()
            {
                active.cancellation_reason = Some(CancellationReason::DeadlineExceeded);
                events.push(AdmissionEvent::ActiveCancellationRequested {
                    request_id: active.lease.request_id().to_owned(),
                    reason: CancellationReason::DeadlineExceeded,
                });
            }
        }
        events
    }

    pub(super) fn dispatch_non_idle(
        &mut self,
        route: ExecutionRoute,
        observed_at: Duration,
        events: &mut Vec<AdmissionEvent>,
    ) {
        while self.active_on_route(route) < ACTIVE_CAPACITY_PER_ROUTE {
            let Some(request_id) = self.pop_weighted(route) else {
                return;
            };
            self.admit_or_reject(request_id, observed_at, events);
        }
    }

    pub(super) fn dispatch_idle(
        &mut self,
        observed_at: Duration,
        events: &mut Vec<AdmissionEvent>,
    ) {
        let route = ExecutionRoute::ComplexOrchestration;
        if self.active_on_route(route) >= ACTIVE_CAPACITY_PER_ROUTE {
            return;
        }
        let active_owners = self.active_owners();
        let request_id = self
            .queues
            .get_mut(&(route, SchedulingClass::IdleOnly))
            .and_then(|queue| queue.pop_dispatchable(&active_owners));
        if let Some(request_id) = request_id {
            self.admit_or_reject(request_id, observed_at, events);
        }
    }

    fn admit_or_reject(
        &mut self,
        request_id: String,
        observed_at: Duration,
        events: &mut Vec<AdmissionEvent>,
    ) {
        let pending = self
            .pending
            .remove(&request_id)
            .expect("queued agent request must exist");
        let request = pending.request;
        let provider_generation = if request.route() == ExecutionRoute::ServerIo {
            None
        } else {
            self.provider_generations.get(&request.route()).copied()
        };
        if request.route() != ExecutionRoute::ServerIo && provider_generation.is_none() {
            self.record_terminal(
                &request,
                TerminalOutcome::ProviderUnavailable(request.route()),
            );
            events.push(AdmissionEvent::ProviderUnavailable {
                request_id,
                route: request.route(),
            });
            return;
        }
        let lease = AdmissionLease {
            request,
            submitted_at: pending.submitted_at,
            admitted_at: observed_at,
            provider_generation,
        };
        events.push(AdmissionEvent::Admitted(lease.clone()));
        self.active.insert(
            request_id,
            ActiveWork {
                lease,
                cancellation_reason: None,
            },
        );
    }

    fn pop_weighted(&mut self, route: ExecutionRoute) -> Option<String> {
        let schedule = priority_schedule(route);
        let cursor = self.priority_cursors.get(&route).copied().unwrap_or(0);
        let active_owners = self.active_owners();
        for offset in 0..schedule.len() {
            let index = (cursor + offset) % schedule.len();
            let class = schedule[index];
            let request_id = self
                .queues
                .get_mut(&(route, class))
                .and_then(|queue| queue.pop_dispatchable(&active_owners));
            if let Some(request_id) = request_id {
                self.priority_cursors
                    .insert(route, (index + 1) % schedule.len());
                return Some(request_id);
            }
        }
        None
    }

    pub(super) fn disrupt_route(&mut self, route: ExecutionRoute) -> Vec<AdmissionEvent> {
        let queued = self
            .pending
            .values()
            .filter(|pending| pending.request.route() == route)
            .map(|pending| pending.request.clone())
            .collect::<Vec<_>>();
        let mut events = Vec::new();
        for request in queued {
            self.remove_pending(&request);
            self.record_terminal(&request, TerminalOutcome::ProviderUnavailable(route));
            events.push(AdmissionEvent::ProviderUnavailable {
                request_id: request.request_id().to_owned(),
                route,
            });
        }
        for active in self
            .active
            .values_mut()
            .filter(|active| active.lease.request.route() == route)
        {
            if active.cancellation_reason.is_none() {
                active.cancellation_reason = Some(CancellationReason::ProviderUnavailable);
                events.push(AdmissionEvent::ActiveCancellationRequested {
                    request_id: active.lease.request_id().to_owned(),
                    reason: CancellationReason::ProviderUnavailable,
                });
            }
        }
        events
    }

    pub(super) fn remove_pending(&mut self, request: &AgentWorkRequest) {
        if let Some(queue) = self
            .queues
            .get_mut(&(request.route(), request.scheduling_class()))
        {
            queue.remove(request.owner(), request.request_id());
        }
        self.pending.remove(request.request_id());
    }

    fn active_on_route(&self, route: ExecutionRoute) -> usize {
        self.active
            .values()
            .filter(|active| active.lease.request.route() == route)
            .count()
    }

    fn active_owners(&self) -> HashSet<WorkOwner> {
        self.active
            .values()
            .map(|active| active.lease.request.owner().clone())
            .collect()
    }

    pub(super) fn non_idle_work_is_absent(&self) -> bool {
        self.pending
            .values()
            .all(|pending| pending.request.scheduling_class() == SchedulingClass::IdleOnly)
            && self
                .active
                .values()
                .all(|active| active.lease.request.scheduling_class() == SchedulingClass::IdleOnly)
    }
}
