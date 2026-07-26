use reqwest::StatusCode;

use super::super::authorization::RequestAuthorizationError;
use super::super::config::ConfigError;

#[derive(Debug)]
pub(crate) enum BatchClientError {
    InvalidOrigin(ConfigError),
    InvalidIdentifier,
    Encode(serde_json::Error),
    Transport(reqwest::Error),
    Authorization(RequestAuthorizationError),
    ResponseTooLarge,
    MalformedResponse,
    InvalidPersistedRequest,
    Api {
        status: StatusCode,
        code: String,
        retryable: bool,
    },
}

impl std::fmt::Display for BatchClientError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidOrigin(error) => write!(formatter, "{error}"),
            Self::InvalidIdentifier => formatter.write_str("Batch request identifier is invalid."),
            Self::Encode(_) => formatter.write_str("Batch request could not be encoded."),
            Self::Transport(error) if error.is_timeout() => {
                formatter.write_str("Batch server request timed out.")
            }
            Self::Transport(_) => formatter.write_str("Batch server request failed."),
            Self::Authorization(RequestAuthorizationError::AccountChanged) => {
                formatter.write_str("The server account changed while remote work was active.")
            }
            Self::Authorization(_) => formatter.write_str("Server sign-in is unavailable."),
            Self::ResponseTooLarge => formatter.write_str("Batch server response is too large."),
            Self::MalformedResponse => {
                formatter.write_str("Batch server returned an incompatible response.")
            }
            Self::InvalidPersistedRequest => {
                formatter.write_str("Prepared batch request is incompatible or corrupt.")
            }
            Self::Api { status, code, .. } => {
                write!(formatter, "{code} (HTTP {})", status.as_u16())
            }
        }
    }
}

impl BatchClientError {
    pub(crate) fn is_retryable(&self) -> bool {
        match self {
            Self::Transport(_) => true,
            Self::Authorization(RequestAuthorizationError::Unavailable) => true,
            Self::Authorization(
                RequestAuthorizationError::InvalidToken | RequestAuthorizationError::AccountChanged,
            ) => false,
            Self::Api { retryable, .. } => *retryable,
            Self::InvalidOrigin(_)
            | Self::InvalidIdentifier
            | Self::Encode(_)
            | Self::ResponseTooLarge
            | Self::MalformedResponse
            | Self::InvalidPersistedRequest => false,
        }
    }
}

impl std::error::Error for BatchClientError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::InvalidOrigin(error) => Some(error),
            Self::Encode(error) => Some(error),
            Self::Transport(error) => Some(error),
            _ => None,
        }
    }
}
