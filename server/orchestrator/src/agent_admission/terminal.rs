use super::{AgentAdmissionScheduler, TerminalOutcome};
use crate::agent_work::AgentWorkRequest;

const MAXIMUM_TERMINAL_REQUESTS: usize = 256;

#[derive(Debug)]
pub(super) struct TerminalWork {
    pub(super) cancellation_token: String,
    pub(super) outcome: TerminalOutcome,
}

impl AgentAdmissionScheduler {
    pub(super) fn record_terminal(&mut self, request: &AgentWorkRequest, outcome: TerminalOutcome) {
        let request_id = request.request_id().to_owned();
        self.terminal_order.retain(|queued| queued != &request_id);
        self.terminal_order.push_back(request_id.clone());
        self.terminal.insert(
            request_id,
            TerminalWork {
                cancellation_token: request.cancellation_token().to_owned(),
                outcome,
            },
        );
        while self.terminal_order.len() > MAXIMUM_TERMINAL_REQUESTS {
            if let Some(expired) = self.terminal_order.pop_front() {
                self.terminal.remove(&expired);
            }
        }
    }

    pub(super) fn terminal_status_matches(
        &self,
        request_id: &str,
        token: &str,
        predicate: impl FnOnce(TerminalOutcome) -> bool,
    ) -> bool {
        self.terminal.get(request_id).is_some_and(|terminal| {
            terminal.cancellation_token == token && predicate(terminal.outcome)
        })
    }
}
