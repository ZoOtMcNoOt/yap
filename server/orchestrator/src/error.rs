use std::fmt;

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct OrchestratorError {
    message: String,
}

impl OrchestratorError {
    pub(crate) fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl fmt::Display for OrchestratorError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for OrchestratorError {}

impl From<std::io::Error> for OrchestratorError {
    fn from(error: std::io::Error) -> Self {
        Self::new(error.to_string())
    }
}

impl From<serde_json::Error> for OrchestratorError {
    fn from(error: serde_json::Error) -> Self {
        Self::new(error.to_string())
    }
}
