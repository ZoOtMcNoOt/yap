use crate::server_connector::{
    terminology::{TerminologyError, TerminologyRequest, TerminologyResponse},
    ServerConnector,
};

static REQUEST: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(1);

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AuthorizedTerminologyResponse {
    authority_revision: String,
    response: TerminologyResponse,
}

fn validate_authority(
    request: &TerminologyRequest,
    expected: Option<&str>,
    current: &str,
) -> Result<(), TerminologyError> {
    let valid = if matches!(request, TerminologyRequest::Discover {}) {
        expected.is_none()
    } else {
        expected == Some(current)
    };
    valid
        .then_some(())
        .ok_or_else(|| TerminologyError::new("identityChanged", false))
}

#[tauri::command]
pub(crate) async fn terminology(
    window: tauri::WebviewWindow,
    connector: tauri::State<'_, ServerConnector>,
    request: TerminologyRequest,
    authority_revision: Option<String>,
) -> Result<AuthorizedTerminologyResponse, TerminologyError> {
    crate::authorization::ensure_main(&window)
        .map_err(|_| TerminologyError::new("denied", false))?;
    let _permit = REQUEST
        .try_acquire()
        .map_err(|_| TerminologyError::new("busy", true))?;
    let lease = connector
        .terminology_connection_lease()
        .map_err(|_| TerminologyError::new("identityChanged", false))?
        .ok_or_else(|| TerminologyError::new("unavailable", true))?;
    let revision = lease.authority_revision();
    validate_authority(&request, authority_revision.as_deref(), &revision)?;
    let result = lease.client().execute(&request).await?;
    connector
        .with_current_terminology_lease(&lease, || AuthorizedTerminologyResponse {
            authority_revision: revision,
            response: result,
        })
        .map_err(|_| TerminologyError::new("identityChanged", false))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_loaded_draft_cannot_dispatch_on_a_new_connection_revision() {
        let request: TerminologyRequest = serde_json::from_value(serde_json::json!({
            "action":"create","scopeId":"personal","mutationId":"11111111-1111-4111-8111-111111111111",
            "locale":"en-US","canonicalForm":"Private draft","variants":["private"],"sensitivity":"internal"
        })).unwrap();
        assert!(validate_authority(&request, Some("7"), "7").is_ok());
        for expected in [None, Some("6"), Some("07")] {
            assert_eq!(
                validate_authority(&request, expected, "7"),
                Err(TerminologyError::new("identityChanged", false))
            );
        }
        assert!(validate_authority(&TerminologyRequest::Discover {}, None, "8").is_ok());
        assert!(validate_authority(&TerminologyRequest::Discover {}, Some("7"), "8").is_err());
    }
}
