#![allow(dead_code)]

use std::time::Duration;

use yap_server_orchestrator::{
    AdmissionEvent, AgentAdmissionScheduler, AgentPurpose, AgentRole, AgentWorkRequest,
    ExecutionRoute, LifecycleState, ProviderRouteIdentity, ProviderService, SchedulingClass,
    ServiceSnapshot, WorkOwner,
};

const RAPID_PROFILE_SHA256: &str =
    "1111111111111111111111111111111111111111111111111111111111111111";
const COMPLEX_PROFILE_SHA256: &str =
    "2222222222222222222222222222222222222222222222222222222222222222";
const CANDIDATE_LOCK_SHA256: &str =
    "3333333333333333333333333333333333333333333333333333333333333333";

pub fn scheduler() -> AgentAdmissionScheduler {
    AgentAdmissionScheduler::new(
        ProviderRouteIdentity::new(
            ProviderService::RapidAutomation,
            RAPID_PROFILE_SHA256.to_owned(),
            CANDIDATE_LOCK_SHA256.to_owned(),
            4,
        )
        .unwrap(),
        ProviderRouteIdentity::new(
            ProviderService::ComplexOrchestration,
            COMPLEX_PROFILE_SHA256.to_owned(),
            CANDIDATE_LOCK_SHA256.to_owned(),
            8,
        )
        .unwrap(),
    )
    .unwrap()
}

pub fn ready_scheduler() -> AgentAdmissionScheduler {
    let mut scheduler = scheduler();
    scheduler
        .observe_provider(&ready_snapshot(ProviderService::RapidAutomation, 1))
        .unwrap();
    scheduler
        .observe_provider(&ready_snapshot(ProviderService::ComplexOrchestration, 1))
        .unwrap();
    scheduler
}

pub fn ready_snapshot(service: ProviderService, process_generation: u64) -> ServiceSnapshot {
    let profile_sha256 = match service {
        ProviderService::RapidAutomation => RAPID_PROFILE_SHA256,
        ProviderService::ComplexOrchestration => COMPLEX_PROFILE_SHA256,
    };
    ServiceSnapshot {
        schema_version: 2,
        service,
        profile_id: service.as_str().to_owned(),
        profile_sha256: profile_sha256.to_owned(),
        candidate_lock_sha256: CANDIDATE_LOCK_SHA256.to_owned(),
        state: LifecycleState::Ready,
        process_generation,
        start_count: process_generation,
        restart_count: process_generation.saturating_sub(1),
        consecutive_failure_count: 0,
        readiness_transition_count: process_generation,
    }
}

pub fn work(
    index: usize,
    subject: &str,
    role: AgentRole,
    deadline_at: Duration,
) -> AgentWorkRequest {
    let (purpose, route, class) = role_binding(role);
    AgentWorkRequest::new(
        request_id(index),
        owner(subject),
        purpose,
        role,
        source_sha(index),
        route,
        class,
        cancellation_token(index),
        deadline_at,
    )
    .unwrap()
}

pub fn role_binding(role: AgentRole) -> (AgentPurpose, ExecutionRoute, SchedulingClass) {
    match role {
        AgentRole::Scribe => (
            AgentPurpose::TranscriptCorrect,
            ExecutionRoute::RapidAutomation,
            SchedulingClass::Hot,
        ),
        AgentRole::Archivist => (
            AgentPurpose::KnowledgeIngest,
            ExecutionRoute::ServerIo,
            SchedulingClass::BackgroundIo,
        ),
        AgentRole::Student => (
            AgentPurpose::LearningQuestions,
            ExecutionRoute::RapidAutomation,
            SchedulingClass::BackgroundLlm,
        ),
        AgentRole::Curator => (
            AgentPurpose::KnowledgePropose,
            ExecutionRoute::ComplexOrchestration,
            SchedulingClass::BackgroundLlm,
        ),
        AgentRole::Auditor => (
            AgentPurpose::KnowledgeAudit,
            ExecutionRoute::ComplexOrchestration,
            SchedulingClass::IdleOnly,
        ),
        AgentRole::Librarian => (
            AgentPurpose::KnowledgeRead,
            ExecutionRoute::ServerIo,
            SchedulingClass::Interactive,
        ),
        AgentRole::Analyst => (
            AgentPurpose::KnowledgeAnswer,
            ExecutionRoute::ComplexOrchestration,
            SchedulingClass::Interactive,
        ),
        AgentRole::Coordinator => (
            AgentPurpose::ConversationCoordinate,
            ExecutionRoute::ComplexOrchestration,
            SchedulingClass::BackgroundLlm,
        ),
    }
}

pub fn owner(subject: &str) -> WorkOwner {
    WorkOwner::new("tenant-a".to_owned(), subject.to_owned()).unwrap()
}

pub fn request_id(index: usize) -> String {
    format!("agent-request-{index}")
}

pub fn cancellation_token(index: usize) -> String {
    format!("{index:064x}")
}

pub fn source_sha(index: usize) -> String {
    format!("{:064x}", index + 1)
}

pub fn admitted_ids(events: Vec<AdmissionEvent>) -> Vec<String> {
    events
        .into_iter()
        .filter_map(|event| match event {
            AdmissionEvent::Admitted(lease) => Some(lease.request_id().to_owned()),
            _ => None,
        })
        .collect()
}

pub fn terminal_ids(events: Vec<AdmissionEvent>) -> Vec<String> {
    events
        .into_iter()
        .filter_map(|event| match event {
            AdmissionEvent::DeadlineExceeded { request_id } => Some(request_id),
            _ => None,
        })
        .collect()
}
