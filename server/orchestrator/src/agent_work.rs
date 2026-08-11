use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::error::OrchestratorError;
use crate::lifecycle::ProviderService;

const MAXIMUM_IDENTITY_CHARACTERS: usize = 128;

#[derive(Debug, Clone, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct WorkOwner {
    tenant_id: String,
    subject_id: String,
}

impl WorkOwner {
    pub fn new(tenant_id: String, subject_id: String) -> Result<Self, OrchestratorError> {
        validate_identity(&tenant_id, "tenant identity")?;
        validate_identity(&subject_id, "subject identity")?;
        Ok(Self {
            tenant_id,
            subject_id,
        })
    }

    pub fn tenant_id(&self) -> &str {
        &self.tenant_id
    }

    pub fn subject_id(&self) -> &str {
        &self.subject_id
    }
}

#[derive(Debug, Clone, Copy, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum AgentRole {
    Scribe,
    Archivist,
    Student,
    Curator,
    Auditor,
    Librarian,
    Analyst,
    Coordinator,
}

#[derive(Debug, Clone, Copy, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum AgentPurpose {
    TranscriptCorrect,
    KnowledgeIngest,
    LearningQuestions,
    KnowledgePropose,
    KnowledgeAudit,
    KnowledgeRead,
    KnowledgeAnswer,
    ConversationCoordinate,
}

#[derive(Debug, Clone, Copy, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum ExecutionRoute {
    ServerIo,
    RapidAutomation,
    ComplexOrchestration,
}

impl ExecutionRoute {
    pub(crate) fn from_provider(service: ProviderService) -> Self {
        match service {
            ProviderService::RapidAutomation => Self::RapidAutomation,
            ProviderService::ComplexOrchestration => Self::ComplexOrchestration,
        }
    }
}

#[derive(Debug, Clone, Copy, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum SchedulingClass {
    Hot,
    Interactive,
    BackgroundIo,
    BackgroundLlm,
    IdleOnly,
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct AgentWorkRequest {
    request_id: String,
    owner: WorkOwner,
    purpose: AgentPurpose,
    role: AgentRole,
    source_sha256: String,
    route: ExecutionRoute,
    scheduling_class: SchedulingClass,
    cancellation_token: String,
    deadline_at: Duration,
}

impl AgentWorkRequest {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        request_id: String,
        owner: WorkOwner,
        purpose: AgentPurpose,
        role: AgentRole,
        source_sha256: String,
        route: ExecutionRoute,
        scheduling_class: SchedulingClass,
        cancellation_token: String,
        deadline_at: Duration,
    ) -> Result<Self, OrchestratorError> {
        validate_request_id(&request_id)?;
        if !is_lower_sha256(&source_sha256) {
            return Err(OrchestratorError::new("agent source identity is invalid"));
        }
        if !is_lower_sha256(&cancellation_token) {
            return Err(OrchestratorError::new(
                "agent cancellation identity is invalid",
            ));
        }
        if deadline_at.is_zero() {
            return Err(OrchestratorError::new("agent deadline is invalid"));
        }
        if !valid_role_binding(role, purpose, route, scheduling_class) {
            return Err(OrchestratorError::new(
                "agent purpose, route, and scheduling class differ from its role",
            ));
        }
        Ok(Self {
            request_id,
            owner,
            purpose,
            role,
            source_sha256,
            route,
            scheduling_class,
            cancellation_token,
            deadline_at,
        })
    }

    pub fn request_id(&self) -> &str {
        &self.request_id
    }

    pub fn owner(&self) -> &WorkOwner {
        &self.owner
    }

    pub fn purpose(&self) -> AgentPurpose {
        self.purpose
    }

    pub fn role(&self) -> AgentRole {
        self.role
    }

    pub fn source_sha256(&self) -> &str {
        &self.source_sha256
    }

    pub fn route(&self) -> ExecutionRoute {
        self.route
    }

    pub fn scheduling_class(&self) -> SchedulingClass {
        self.scheduling_class
    }

    pub fn cancellation_token(&self) -> &str {
        &self.cancellation_token
    }

    pub fn deadline_at(&self) -> Duration {
        self.deadline_at
    }
}

fn valid_role_binding(
    role: AgentRole,
    purpose: AgentPurpose,
    route: ExecutionRoute,
    scheduling_class: SchedulingClass,
) -> bool {
    match role {
        AgentRole::Scribe => {
            purpose == AgentPurpose::TranscriptCorrect
                && route == ExecutionRoute::RapidAutomation
                && scheduling_class == SchedulingClass::Hot
        }
        AgentRole::Archivist => {
            purpose == AgentPurpose::KnowledgeIngest
                && route == ExecutionRoute::ServerIo
                && scheduling_class == SchedulingClass::BackgroundIo
        }
        AgentRole::Student => {
            purpose == AgentPurpose::LearningQuestions
                && route == ExecutionRoute::RapidAutomation
                && scheduling_class == SchedulingClass::BackgroundLlm
        }
        AgentRole::Curator => {
            purpose == AgentPurpose::KnowledgePropose
                && route == ExecutionRoute::ComplexOrchestration
                && scheduling_class == SchedulingClass::BackgroundLlm
        }
        AgentRole::Auditor => {
            purpose == AgentPurpose::KnowledgeAudit
                && route == ExecutionRoute::ComplexOrchestration
                && scheduling_class == SchedulingClass::IdleOnly
        }
        AgentRole::Librarian => {
            purpose == AgentPurpose::KnowledgeRead
                && route == ExecutionRoute::ServerIo
                && scheduling_class == SchedulingClass::Interactive
        }
        AgentRole::Analyst => {
            purpose == AgentPurpose::KnowledgeAnswer
                && matches!(
                    route,
                    ExecutionRoute::RapidAutomation | ExecutionRoute::ComplexOrchestration
                )
                && scheduling_class == SchedulingClass::Interactive
        }
        AgentRole::Coordinator => {
            purpose == AgentPurpose::ConversationCoordinate
                && route == ExecutionRoute::ComplexOrchestration
                && scheduling_class == SchedulingClass::BackgroundLlm
        }
    }
}

fn validate_identity(value: &str, component: &str) -> Result<(), OrchestratorError> {
    if value.is_empty()
        || value.len() > MAXIMUM_IDENTITY_CHARACTERS
        || value.trim() != value
        || !value.is_ascii()
        || !value.chars().all(|value| value.is_ascii_graphic())
    {
        return Err(OrchestratorError::new(format!("{component} is invalid")));
    }
    Ok(())
}

fn validate_request_id(value: &str) -> Result<(), OrchestratorError> {
    if value.is_empty()
        || value.len() > MAXIMUM_IDENTITY_CHARACTERS
        || !value.bytes().enumerate().all(|(index, value)| {
            value.is_ascii_alphanumeric() || (index > 0 && matches!(value, b'.' | b'_' | b'-'))
        })
    {
        return Err(OrchestratorError::new("agent request identity is invalid"));
    }
    Ok(())
}

pub(crate) fn is_lower_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|value| value.is_ascii_digit() || (b'a'..=b'f').contains(&value))
}
