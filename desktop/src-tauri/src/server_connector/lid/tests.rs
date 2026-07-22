use std::{
    io::{Read, Write},
    net::TcpListener,
    time::Duration,
};

use crate::server_connector::{
    batch::{BatchApiClient, SourceVadInterval},
    client::bounded_client,
    AsrCapabilityCatalog,
};

use super::{
    select_lid_probe_windows, LidManualReason, LidPreflightRequest, LidPreflightSourceIdentity,
    LidPreflightStatus,
};

const CATALOG_REVISION: &str = "16a89b24cf036dda7b1272b88c066baafea2262743dcaaebc8a66b7b76c3d09f";
const SOURCE_PCM_SHA256: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const FIRST_WAV_SHA256: &str = "2fab96a5c20b3675930a4a32b5c9f3528b398cbc5e456c102b5fb76f23941f21";
const SECOND_WAV_SHA256: &str = "9644fe8b8d4790dfc2213331f1317fdcf1660598bcb830d572eabd187fe3d75f";

#[test]
fn selector_matches_the_accepted_two_window_policy_and_fails_manual() {
    let catalog = catalog_with_lid();
    let capability = catalog.lid_preflight().unwrap();
    let full_voice = vec![SourceVadInterval::from_samples(0, 480_000).unwrap()];
    let selection = select_lid_probe_windows(capability, 480_000, &full_voice).unwrap();
    let windows = selection.windows().unwrap();
    assert_eq!(windows[0].source_start_sample(), 0);
    assert_eq!(windows[0].source_end_sample(), 240_000);
    assert_eq!(windows[1].source_start_sample(), 240_000);
    assert_eq!(windows[1].source_end_sample(), 480_000);
    assert_eq!(windows[0].voiced_samples(), 240_000);
    assert_eq!(windows[1].voiced_samples(), 240_000);

    let short = select_lid_probe_windows(capability, 479_999, &[]).unwrap();
    assert_eq!(short.manual_reason(), Some(LidManualReason::ShortRecording));
    let one_probe = vec![SourceVadInterval::from_samples(0, 160_000).unwrap()];
    let manual = select_lid_probe_windows(capability, 960_000, &one_probe).unwrap();
    assert_eq!(
        manual.manual_reason(),
        Some(LidManualReason::SecondProbeUnavailable)
    );
}

#[test]
fn envelope_is_bounded_digest_bound_and_contains_no_local_paths() {
    let request = request_fixture();
    let body = request.body();
    let manifest_length = u32::from_be_bytes(body[..4].try_into().unwrap()) as usize;
    let manifest: serde_json::Value =
        serde_json::from_slice(&body[4..4 + manifest_length]).unwrap();

    assert_eq!(manifest["schemaVersion"], 1);
    assert_eq!(manifest["requestId"], "job-lid-client");
    assert_eq!(manifest["sourcePcmSha256"], SOURCE_PCM_SHA256);
    assert_eq!(manifest["catalogRevision"], CATALOG_REVISION);
    assert_eq!(manifest["policyRevision"], "speechbrain-two-window-v1");
    assert_eq!(manifest["probes"].as_array().unwrap().len(), 2);
    assert_eq!(
        manifest["probes"][0]["pcmSha256"],
        "bad662ada862615b24543db809a1d3774caf4cd54adf33612606a53334371294"
    );
    assert_eq!(body.len(), 4 + manifest_length + 960_000);
    let encoded = String::from_utf8_lossy(&body[..4 + manifest_length]);
    assert!(!encoded.contains("C:\\"));
    assert!(!encoded.contains("/tmp/"));
}

#[test]
fn response_is_rebound_to_source_component_policy_and_server_decision() {
    let request = request_fixture();
    let body = serde_json::to_vec(&valid_response()).unwrap();
    let result = request.decode_response(&body).unwrap();

    assert_eq!(result.status, LidPreflightStatus::Suggestion);
    assert_eq!(result.suggested_locale.as_deref(), Some("en-US"));
    assert!(result.user_confirmation_required);
    assert_eq!(result.observations.len(), 2);
    assert_eq!(result.observations[0].probe_sha256, FIRST_WAV_SHA256);

    for mutation in ["source", "policy", "mapping", "confirmation"] {
        let mut invalid = valid_response();
        match mutation {
            "source" => invalid["sourcePcmSha256"] = serde_json::Value::String("b".repeat(64)),
            "policy" => {
                invalid["component"]["scoreSemantics"] = serde_json::Value::String("unknown".into())
            }
            "mapping" => invalid["observations"][0]["mappedLocale"] = serde_json::Value::Null,
            "confirmation" => invalid["userConfirmationRequired"] = serde_json::Value::Bool(false),
            _ => unreachable!(),
        }
        assert!(request
            .decode_response(&serde_json::to_vec(&invalid).unwrap())
            .is_err());
    }
}

#[test]
fn native_client_uses_versioned_media_type_and_validates_success() {
    let request = request_fixture();
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let response_body = serde_json::to_vec(&valid_response()).unwrap();
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        let request = read_http_request(&mut stream);
        let header_end = find_header_end(&request).unwrap();
        let headers = String::from_utf8_lossy(&request[..header_end]);
        assert!(headers.starts_with("POST /v1/lid/preflight HTTP/1.1"));
        assert!(headers
            .to_ascii_lowercase()
            .contains("content-type: application/vnd.yap.lid-preflight.v1+octet-stream"));
        write_json_response(&mut stream, 200, "OK", &response_body);
    });
    let client =
        BatchApiClient::new(bounded_client().unwrap(), &format!("http://{address}")).unwrap();

    let result = tauri::async_runtime::block_on(client.lid_preflight(&request)).unwrap();
    server.join().unwrap();
    assert_eq!(result.suggested_locale.as_deref(), Some("en-US"));
}

#[test]
fn cancellation_and_retryable_api_errors_remain_typed() {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let request = read_http_request(&mut stream);
        assert!(String::from_utf8_lossy(&request)
            .starts_with("DELETE /v1/lid/preflights/job-lid-client HTTP/1.1"));
        let body = br#"{"schemaVersion":1,"requestId":"job-lid-client","status":"cancellation_requested"}"#;
        write_json_response(&mut stream, 202, "Accepted", body);
    });
    let client =
        BatchApiClient::new(bounded_client().unwrap(), &format!("http://{address}")).unwrap();
    tauri::async_runtime::block_on(client.cancel_lid_preflight("job-lid-client")).unwrap();
    server.join().unwrap();

    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let address = listener.local_addr().unwrap();
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let _ = read_http_request(&mut stream);
        let body = br#"{"code":"LID_PREFLIGHT_BUSY","message":"Try again.","retryable":true,"requestId":"request-1"}"#;
        write_json_response(&mut stream, 429, "Too Many Requests", body);
    });
    let client =
        BatchApiClient::new(bounded_client().unwrap(), &format!("http://{address}")).unwrap();
    let error =
        tauri::async_runtime::block_on(client.lid_preflight(&request_fixture())).unwrap_err();
    server.join().unwrap();
    assert!(error.is_retryable());
}

fn request_fixture() -> LidPreflightRequest {
    let catalog = catalog_with_lid();
    let intervals = vec![SourceVadInterval::from_samples(0, 480_000).unwrap()];
    let selection =
        select_lid_probe_windows(catalog.lid_preflight().unwrap(), 480_000, &intervals).unwrap();
    LidPreflightRequest::from_selected_probes(
        &catalog,
        LidPreflightSourceIdentity::try_new(
            "job-lid-client".into(),
            480_000,
            SOURCE_PCM_SHA256.into(),
        )
        .unwrap(),
        &selection,
        [b"\x01\x00".repeat(240_000), b"\x02\x00".repeat(240_000)],
    )
    .unwrap()
}

fn catalog_with_lid() -> AsrCapabilityCatalog {
    let mut value: serde_json::Value = serde_json::from_slice(include_bytes!(
        "../../../../../server/openapi/examples/asr-capabilities.ok.json"
    ))
    .unwrap();
    value["languagePreflight"] = serde_json::json!({
        "schemaVersion": 1,
        "componentId": "speechbrain-lid-preflight",
        "runtime": {"pythonVersion": "3.12.13", "cpuOnly": true},
        "model": {
            "id": "speechbrain/lang-id-voxlingua107-ecapa",
            "revision": "0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9"
        },
        "transport": {
            "mediaType": "application/vnd.yap.lid-preflight.v1+octet-stream",
            "maximumBodyBytes": 1_048_576,
            "maximumManifestBytes": 32_768,
            "maximumResponseSeconds": 120
        },
        "policy": {
            "revision": "speechbrain-two-window-v1",
            "sampleRateHz": 16_000,
            "channelCount": 1,
            "sampleWidthBytes": 2,
            "minimumSourceSamples": 480_000,
            "maximumWindows": 2,
            "maximumWindowSamples": 240_000,
            "minimumVoicedSamplesPerWindow": 128_000,
            "scoreSemantics": "uncalibrated-log-posterior",
            "userConfirmationRequired": true
        }
    });
    AsrCapabilityCatalog::parse_bounded(&serde_json::to_vec(&value).unwrap()).unwrap()
}

fn valid_response() -> serde_json::Value {
    serde_json::json!({
        "schemaVersion": 1,
        "requestId": "job-lid-client",
        "status": "suggestion",
        "reason": "mapped_language_agreement",
        "suggestedLocale": "en-US",
        "userConfirmationRequired": true,
        "sourceSamples": 480_000,
        "sourcePcmSha256": SOURCE_PCM_SHA256,
        "catalogRevision": CATALOG_REVISION,
        "component": {
            "id": "speechbrain-lid-preflight",
            "runtime": {"pythonVersion": "3.12.13", "cpuOnly": true},
            "model": {
                "id": "speechbrain/lang-id-voxlingua107-ecapa",
                "revision": "0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9"
            },
            "policyRevision": "speechbrain-two-window-v1",
            "scoreSemantics": "uncalibrated-log-posterior"
        },
        "observations": [
            {
                "index": 0,
                "probeSha256": FIRST_WAV_SHA256,
                "sourceStartSample": 0,
                "sourceEndSample": 240_000,
                "voicedSamples": 240_000,
                "rawLabel": "en: English",
                "topScore": -0.1,
                "scoreMargin": 1.0,
                "mappedLocale": "en-US"
            },
            {
                "index": 1,
                "probeSha256": SECOND_WAV_SHA256,
                "sourceStartSample": 240_000,
                "sourceEndSample": 480_000,
                "voicedSamples": 240_000,
                "rawLabel": "en: English",
                "topScore": -0.2,
                "scoreMargin": 0.9,
                "mappedLocale": "en-US"
            }
        ]
    })
}

fn read_http_request(stream: &mut std::net::TcpStream) -> Vec<u8> {
    let mut request = Vec::new();
    let mut buffer = [0_u8; 16 * 1024];
    loop {
        let read = stream.read(&mut buffer).unwrap();
        if read == 0 {
            break;
        }
        request.extend_from_slice(&buffer[..read]);
        let Some(header_end) = find_header_end(&request) else {
            continue;
        };
        let headers = String::from_utf8_lossy(&request[..header_end]);
        let content_length = headers
            .lines()
            .find_map(|line| {
                line.split_once(':').and_then(|(name, value)| {
                    name.eq_ignore_ascii_case("content-length")
                        .then(|| value.trim().parse::<usize>().unwrap())
                })
            })
            .unwrap_or(0);
        if request.len() >= header_end + 4 + content_length {
            break;
        }
    }
    request
}

fn find_header_end(request: &[u8]) -> Option<usize> {
    request.windows(4).position(|window| window == b"\r\n\r\n")
}

fn write_json_response(stream: &mut std::net::TcpStream, status: u16, reason: &str, body: &[u8]) {
    let headers = format!(
        "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(headers.as_bytes()).unwrap();
    stream.write_all(body).unwrap();
}
