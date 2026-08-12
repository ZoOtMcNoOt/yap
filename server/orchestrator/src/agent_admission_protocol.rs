use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::agent_admission::{
    AdmissionDecision, AdmissionStatus, AgentAdmissionScheduler, TerminalOutcome,
};
use crate::agent_work::{
    AgentPurpose, AgentRole, AgentWorkRequest, ExecutionRoute, SchedulingClass, WorkOwner,
};

const PROTOCOL_SCHEMA_VERSION: u8 = 1;
pub(crate) const MAXIMUM_REQUEST_BYTES: usize = 16 * 1024;

#[derive(Debug, Deserialize)]
#[serde(
    tag = "command",
    rename_all = "kebab-case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
enum AgentAdmissionCommand {
    Submit {
        schema_version: u8,
        request_id: String,
        tenant_id: String,
        subject_id: String,
        purpose: AgentPurpose,
        role: AgentRole,
        source_sha256: String,
        route: ExecutionRoute,
        scheduling_class: SchedulingClass,
        cancellation_token: String,
        remaining_deadline_ms: u64,
    },
    Status {
        schema_version: u8,
        request_id: String,
        cancellation_token: String,
    },
    Cancel {
        schema_version: u8,
        request_id: String,
        cancellation_token: String,
    },
    Complete {
        schema_version: u8,
        request_id: String,
        cancellation_token: String,
    },
    AcknowledgeCancellation {
        schema_version: u8,
        request_id: String,
        cancellation_token: String,
    },
}

#[derive(Debug, Serialize)]
#[serde(
    tag = "outcome",
    rename_all = "kebab-case",
    rename_all_fields = "camelCase"
)]
enum AgentAdmissionResponse {
    Queued {
        schema_version: u8,
    },
    Admitted {
        schema_version: u8,
        route: ExecutionRoute,
        provider_generation: Option<u64>,
        queue_duration_ms: u64,
    },
    CancellationRequested {
        schema_version: u8,
        reason: crate::agent_admission::CancellationReason,
    },
    Completed {
        schema_version: u8,
    },
    Cancelled {
        schema_version: u8,
    },
    DeadlineExceeded {
        schema_version: u8,
    },
    ProviderUnavailable {
        schema_version: u8,
        route: ExecutionRoute,
    },
    DuplicateRequest {
        schema_version: u8,
    },
    OwnerQueueFull {
        schema_version: u8,
    },
    QueueFull {
        schema_version: u8,
    },
    #[cfg(unix)]
    BrokerBusy {
        schema_version: u8,
    },
    NotFoundOrUnauthorized {
        schema_version: u8,
    },
    InvalidRequest {
        schema_version: u8,
    },
}

#[cfg(unix)]
pub(crate) fn agent_admission_busy_response() -> Vec<u8> {
    response_bytes(AgentAdmissionResponse::BrokerBusy {
        schema_version: PROTOCOL_SCHEMA_VERSION,
    })
}

pub fn process_agent_admission_request(
    scheduler: &mut AgentAdmissionScheduler,
    request_bytes: &[u8],
    observed_at: Duration,
) -> Vec<u8> {
    let response = parse_command(request_bytes)
        .and_then(|command| handle_command(scheduler, command, observed_at))
        .unwrap_or(AgentAdmissionResponse::InvalidRequest {
            schema_version: PROTOCOL_SCHEMA_VERSION,
        });
    response_bytes(response)
}

fn response_bytes(response: AgentAdmissionResponse) -> Vec<u8> {
    let mut bytes = serde_json::to_vec(&response).expect("admission response is serializable");
    bytes.push(b'\n');
    bytes
}

fn parse_command(request_bytes: &[u8]) -> Option<AgentAdmissionCommand> {
    if request_bytes.is_empty()
        || request_bytes.len() > MAXIMUM_REQUEST_BYTES
        || !request_bytes.ends_with(b"\n")
        || request_bytes[..request_bytes.len() - 1].contains(&b'\n')
    {
        return None;
    }
    serde_json::from_slice(&request_bytes[..request_bytes.len() - 1]).ok()
}

fn handle_command(
    scheduler: &mut AgentAdmissionScheduler,
    command: AgentAdmissionCommand,
    observed_at: Duration,
) -> Option<AgentAdmissionResponse> {
    scheduler.dispatch(observed_at);
    match command {
        AgentAdmissionCommand::Submit {
            schema_version,
            request_id,
            tenant_id,
            subject_id,
            purpose,
            role,
            source_sha256,
            route,
            scheduling_class,
            cancellation_token,
            remaining_deadline_ms,
        } => {
            require_schema(schema_version)?;
            if remaining_deadline_ms == 0
                || remaining_deadline_ms > maximum_deadline_ms(scheduling_class)
            {
                return None;
            }
            let deadline_at =
                observed_at.checked_add(Duration::from_millis(remaining_deadline_ms))?;
            let request = AgentWorkRequest::new(
                request_id.clone(),
                WorkOwner::new(tenant_id, subject_id).ok()?,
                purpose,
                role,
                source_sha256,
                route,
                scheduling_class,
                cancellation_token.clone(),
                deadline_at,
            )
            .ok()?;
            match scheduler.submit(request, observed_at) {
                AdmissionDecision::Queued => {
                    scheduler.dispatch(observed_at);
                    Some(response_for_status(
                        scheduler.status(&request_id, &cancellation_token),
                    ))
                }
                decision => Some(response_for_decision(decision)),
            }
        }
        AgentAdmissionCommand::Status {
            schema_version,
            request_id,
            cancellation_token,
        } => {
            require_schema(schema_version)?;
            Some(response_for_status(
                scheduler.status(&request_id, &cancellation_token),
            ))
        }
        AgentAdmissionCommand::Cancel {
            schema_version,
            request_id,
            cancellation_token,
        } => {
            require_schema(schema_version)?;
            scheduler.cancel(&request_id, &cancellation_token);
            Some(response_for_status(
                scheduler.status(&request_id, &cancellation_token),
            ))
        }
        AgentAdmissionCommand::Complete {
            schema_version,
            request_id,
            cancellation_token,
        } => {
            require_schema(schema_version)?;
            if scheduler
                .complete(&request_id, &cancellation_token)
                .is_err()
            {
                return Some(response_for_status(
                    scheduler.status(&request_id, &cancellation_token),
                ));
            }
            Some(response_for_status(
                scheduler.status(&request_id, &cancellation_token),
            ))
        }
        AgentAdmissionCommand::AcknowledgeCancellation {
            schema_version,
            request_id,
            cancellation_token,
        } => {
            require_schema(schema_version)?;
            if scheduler
                .acknowledge_cancellation(&request_id, &cancellation_token)
                .is_err()
            {
                return Some(response_for_status(
                    scheduler.status(&request_id, &cancellation_token),
                ));
            }
            Some(response_for_status(
                scheduler.status(&request_id, &cancellation_token),
            ))
        }
    }
}

fn response_for_decision(decision: AdmissionDecision) -> AgentAdmissionResponse {
    let schema_version = PROTOCOL_SCHEMA_VERSION;
    match decision {
        AdmissionDecision::Queued => AgentAdmissionResponse::Queued { schema_version },
        AdmissionDecision::ProviderUnavailable(route) => {
            AgentAdmissionResponse::ProviderUnavailable {
                schema_version,
                route,
            }
        }
        AdmissionDecision::DeadlineExceeded => {
            AgentAdmissionResponse::DeadlineExceeded { schema_version }
        }
        AdmissionDecision::DuplicateRequest => {
            AgentAdmissionResponse::DuplicateRequest { schema_version }
        }
        AdmissionDecision::NotFoundOrUnauthorized => {
            AgentAdmissionResponse::NotFoundOrUnauthorized { schema_version }
        }
        AdmissionDecision::OwnerQueueFull => {
            AgentAdmissionResponse::OwnerQueueFull { schema_version }
        }
        AdmissionDecision::QueueFull => AgentAdmissionResponse::QueueFull { schema_version },
    }
}

fn response_for_status(status: AdmissionStatus) -> AgentAdmissionResponse {
    let schema_version = PROTOCOL_SCHEMA_VERSION;
    match status {
        AdmissionStatus::Queued => AgentAdmissionResponse::Queued { schema_version },
        AdmissionStatus::Admitted(lease) => AgentAdmissionResponse::Admitted {
            schema_version,
            route: lease.request().route(),
            provider_generation: lease.provider_generation(),
            queue_duration_ms: lease.queue_duration().as_millis() as u64,
        },
        AdmissionStatus::ActiveCancellationRequested(reason) => {
            AgentAdmissionResponse::CancellationRequested {
                schema_version,
                reason,
            }
        }
        AdmissionStatus::Terminal(outcome) => match outcome {
            TerminalOutcome::Completed => AgentAdmissionResponse::Completed { schema_version },
            TerminalOutcome::Cancelled => AgentAdmissionResponse::Cancelled { schema_version },
            TerminalOutcome::DeadlineExceeded => {
                AgentAdmissionResponse::DeadlineExceeded { schema_version }
            }
            TerminalOutcome::ProviderUnavailable(route) => {
                AgentAdmissionResponse::ProviderUnavailable {
                    schema_version,
                    route,
                }
            }
        },
        AdmissionStatus::NotFoundOrUnauthorized => {
            AgentAdmissionResponse::NotFoundOrUnauthorized { schema_version }
        }
    }
}

fn require_schema(schema_version: u8) -> Option<()> {
    (schema_version == PROTOCOL_SCHEMA_VERSION).then_some(())
}

fn maximum_deadline_ms(class: SchedulingClass) -> u64 {
    match class {
        SchedulingClass::Hot => 60_000,
        SchedulingClass::Interactive => 120_000,
        SchedulingClass::BackgroundIo
        | SchedulingClass::BackgroundLlm
        | SchedulingClass::IdleOnly => 300_000,
    }
}
