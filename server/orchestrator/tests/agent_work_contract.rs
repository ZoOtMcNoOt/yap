use std::time::Duration;

use yap_server_orchestrator::{
    AgentPurpose, AgentRole, AgentWorkRequest, ExecutionRoute, SchedulingClass, WorkOwner,
};

#[test]
fn every_agent_role_has_one_exact_purpose_route_and_scheduling_class() {
    let roles = [
        AgentRole::Scribe,
        AgentRole::Archivist,
        AgentRole::Student,
        AgentRole::Curator,
        AgentRole::Auditor,
        AgentRole::Librarian,
        AgentRole::Analyst,
        AgentRole::Coordinator,
    ];

    for (index, role) in roles.into_iter().enumerate() {
        let (purpose, route, class) = role_binding(role);
        AgentWorkRequest::new(
            request_id(index),
            owner("alice"),
            purpose,
            role,
            source_sha(index),
            route,
            class,
            cancellation_token(index),
            Duration::from_secs(30),
        )
        .unwrap();

        let wrong_route = match role {
            AgentRole::Scribe | AgentRole::Student => ExecutionRoute::ComplexOrchestration,
            AgentRole::Analyst => ExecutionRoute::ServerIo,
            _ => ExecutionRoute::RapidAutomation,
        };
        assert!(AgentWorkRequest::new(
            request_id(index + 20),
            owner("alice"),
            purpose,
            role,
            source_sha(index),
            wrong_route,
            class,
            cancellation_token(index + 20),
            Duration::from_secs(30),
        )
        .is_err());
    }

    AgentWorkRequest::new(
        request_id(100),
        owner("alice"),
        AgentPurpose::KnowledgeAnswer,
        AgentRole::Analyst,
        source_sha(100),
        ExecutionRoute::RapidAutomation,
        SchedulingClass::Interactive,
        cancellation_token(100),
        Duration::from_secs(30),
    )
    .unwrap();
}

fn role_binding(role: AgentRole) -> (AgentPurpose, ExecutionRoute, SchedulingClass) {
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

fn owner(subject: &str) -> WorkOwner {
    WorkOwner::new("tenant-a".to_owned(), subject.to_owned()).unwrap()
}

fn request_id(index: usize) -> String {
    format!("agent-request-{index}")
}

fn cancellation_token(index: usize) -> String {
    format!("{index:064x}")
}

fn source_sha(index: usize) -> String {
    format!("{:064x}", index + 1)
}
