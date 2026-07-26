use reqwest::StatusCode;

#[derive(Debug)]
pub(crate) enum LidPreflightError {
    InvalidRequest(&'static str),
    Encode(serde_json::Error),
    Transport(reqwest::Error),
    ResponseTooLarge,
    MalformedResponse,
    Api {
        status: StatusCode,
        code: String,
        retryable: bool,
    },
}

impl LidPreflightError {
    pub(crate) fn invalid(reason: &'static str) -> Self {
        Self::InvalidRequest(reason)
    }

    pub(crate) fn is_retryable(&self) -> bool {
        match self {
            Self::Transport(_) => true,
            Self::Api { retryable, .. } => *retryable,
            Self::InvalidRequest(_)
            | Self::Encode(_)
            | Self::ResponseTooLarge
            | Self::MalformedResponse => false,
        }
    }

    pub(crate) fn is_not_found(&self) -> bool {
        matches!(
            self,
            Self::Api { status, code, .. }
                if *status == StatusCode::NOT_FOUND && code == "LID_PREFLIGHT_NOT_FOUND"
        )
    }
}

impl std::fmt::Display for LidPreflightError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidRequest(reason) => {
                write!(formatter, "Language preflight is invalid: {reason}.")
            }
            Self::Encode(_) => formatter.write_str("Language preflight could not be encoded."),
            Self::Transport(error) if error.is_timeout() => {
                formatter.write_str("Language preflight timed out.")
            }
            Self::Transport(_) => formatter.write_str("Language preflight request failed."),
            Self::ResponseTooLarge => {
                formatter.write_str("Language preflight response is too large.")
            }
            Self::MalformedResponse => {
                formatter.write_str("Language preflight returned incompatible evidence.")
            }
            Self::Api { status, code, .. } => {
                write!(formatter, "{code} (HTTP {})", status.as_u16())
            }
        }
    }
}

impl std::error::Error for LidPreflightError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Encode(error) => Some(error),
            Self::Transport(error) => Some(error),
            _ => None,
        }
    }
}
