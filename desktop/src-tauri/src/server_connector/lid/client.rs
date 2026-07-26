use reqwest::{Client, Response, StatusCode, Url};

use crate::server_connector::batch::ApiError;

use super::{
    envelope::valid_request_id, LidPreflightError, LidPreflightRequest, LidPreflightResult,
};

const MAX_LID_RESPONSE_BYTES: usize = 128 * 1024;
const MAX_CANCEL_RESPONSE_BYTES: usize = 16 * 1024;

pub(in crate::server_connector) async fn submit_preflight(
    client: &Client,
    base_url: &Url,
    request: &LidPreflightRequest,
) -> Result<LidPreflightResult, LidPreflightError> {
    let response = client
        .post(endpoint(base_url, &["lid", "preflight"])?)
        .header(reqwest::header::ACCEPT, "application/json")
        .header(reqwest::header::CONTENT_TYPE, request.media_type())
        .timeout(request.timeout())
        .body(request.body().to_vec())
        .send()
        .await
        .map_err(LidPreflightError::Transport)?;
    let status = response.status();
    let body = read_bounded(response, MAX_LID_RESPONSE_BYTES).await?;
    if status != StatusCode::OK {
        return Err(decode_api_error(status, &body));
    }
    request.decode_response(&body)
}

pub(in crate::server_connector) async fn cancel_preflight(
    client: &Client,
    base_url: &Url,
    request_id: &str,
) -> Result<(), LidPreflightError> {
    if !valid_request_id(request_id) {
        return Err(LidPreflightError::invalid("request ID is invalid"));
    }
    let response = client
        .delete(endpoint(base_url, &["lid", "preflights", request_id])?)
        .header(reqwest::header::ACCEPT, "application/json")
        .send()
        .await
        .map_err(LidPreflightError::Transport)?;
    let status = response.status();
    let body = read_bounded(response, MAX_CANCEL_RESPONSE_BYTES).await?;
    if status != StatusCode::ACCEPTED {
        return Err(decode_api_error(status, &body));
    }
    let acknowledgement: CancellationAcknowledgement =
        serde_json::from_slice(&body).map_err(|_| LidPreflightError::MalformedResponse)?;
    if acknowledgement.schema_version != 1
        || acknowledgement.request_id != request_id
        || acknowledgement.status != "cancellation_requested"
    {
        return Err(LidPreflightError::MalformedResponse);
    }
    Ok(())
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CancellationAcknowledgement {
    schema_version: u16,
    request_id: String,
    status: String,
}

fn endpoint(base_url: &Url, segments: &[&str]) -> Result<Url, LidPreflightError> {
    let mut url = base_url.clone();
    {
        let mut path = url
            .path_segments_mut()
            .map_err(|_| LidPreflightError::invalid("server origin cannot hold a path"))?;
        path.clear().push("v1");
        for segment in segments {
            path.push(segment);
        }
    }
    Ok(url)
}

async fn read_bounded(
    mut response: Response,
    maximum_bytes: usize,
) -> Result<Vec<u8>, LidPreflightError> {
    if response
        .content_length()
        .is_some_and(|length| length > maximum_bytes as u64)
    {
        return Err(LidPreflightError::ResponseTooLarge);
    }
    let mut body = Vec::with_capacity(
        response
            .content_length()
            .unwrap_or_default()
            .min(maximum_bytes as u64) as usize,
    );
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(LidPreflightError::Transport)?
    {
        if body.len().saturating_add(chunk.len()) > maximum_bytes {
            return Err(LidPreflightError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn decode_api_error(status: StatusCode, body: &[u8]) -> LidPreflightError {
    let Ok(error) = serde_json::from_slice::<ApiError>(body) else {
        return LidPreflightError::MalformedResponse;
    };
    if !error.is_valid() {
        return LidPreflightError::MalformedResponse;
    }
    LidPreflightError::Api {
        status,
        code: error.code,
        retryable: error.retryable,
    }
}
