use std::{
    io::{Read, Write},
    net::TcpListener,
    time::Duration,
};

use crate::server_connector::{
    batch::{BatchApiClient, SourceVadInterval},
    client::bounded_client,
    AsrCapabilityCatalog, RequestAuthorization,
};

use super::{
    select_lid_probe_windows, LidManualReason, LidPreflightRequest, LidPreflightSourceIdentity,
    LidPreflightStatus,
};

const CATALOG_REVISION: &str = "16a89b24cf036dda7b1272b88c066baafea2262743dcaaebc8a66b7b76c3d09f";
const SOURCE_PCM_SHA256: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const REGION_WAV_SHA256: &str = "5ec432a9c59a66bf04f259cc63fe1cbe954133cc13792b1bbb57d485db18bb94";

#[test]
fn selector_spans_five_regions_and_fails_manual_when_one_lacks_speech() {
    let catalog = catalog_with_lid();
    let capability = catalog.lid_preflight().unwrap();
    let full_voice = vec![SourceVadInterval::from_samples(0, 480_000).unwrap()];
    let selection = select_lid_probe_windows(capability, 480_000, &full_voice).unwrap();
    let windows = selection.windows().unwrap();
    assert_eq!(windows[0].source_start_sample(), 0);
    assert_eq!(windows.len(), 5);
    for (index, window) in windows.iter().enumerate() {
        assert_eq!(window.source_start_sample(), index as u64 * 96_000);
        assert_eq!(window.source_end_sample(), (index as u64 + 1) * 96_000);
        assert_eq!(window.voiced_samples(), 96_000);
    }

    let short = select_lid_probe_windows(capability, 479_999, &[]).unwrap();
    assert_eq!(short.manual_reason(), Some(LidManualReason::ShortRecording));
    let missing_middle = vec![
        SourceVadInterval::from_samples(0, 192_000).unwrap(),
        SourceVadInterval::from_samples(288_000, 480_000).unwrap(),
    ];
    let manual = select_lid_probe_windows(capability, 480_000, &missing_middle).unwrap();
    assert_eq!(
        manual.manual_reason(),
        Some(LidManualReason::StratifiedRegionUnavailable)
    );

    let long_samples = 16_000 * 4 * 60 * 60;
    let long_voice = vec![SourceVadInterval::from_samples(0, long_samples).unwrap()];
    let long = select_lid_probe_windows(capability, long_samples, &long_voice).unwrap();
    let long_windows = long.windows().unwrap();
    assert_eq!(long_windows[0].source_start_sample(), 0);
    assert_eq!(
        long_windows[4].source_end_sample(),
        long_samples,
        "the fifth region must cover the exact recording tail"
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
    assert_eq!(
        manifest["policyRevision"],
        "ambernet-stratified-five-region-v1"
    );
    assert_eq!(manifest["probes"].as_array().unwrap().len(), 5);
    assert_eq!(
        manifest["probes"][0]["pcmSha256"],
        "9257719ca0fe28b5431d68d79957cbfe09d367593ccf2a115ba20193e8a7dfdc"
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
    assert_eq!(result.observations.len(), 5);
    assert_eq!(result.observations[0].probe_sha256, REGION_WAV_SHA256);

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

    let mut disagreement = valid_response();
    disagreement["status"] = "manual".into();
    disagreement["reason"] = "language_disagreement".into();
    disagreement["suggestedLocale"] = serde_json::Value::Null;
    disagreement["observations"][4]["rawLabel"] = "zz".into();
    disagreement["observations"][4]["mappedLocale"] = serde_json::Value::Null;
    assert_eq!(
        request
            .decode_response(&serde_json::to_vec(&disagreement).unwrap())
            .unwrap()
            .status,
        LidPreflightStatus::Manual
    );

    let mut ambiguous = valid_response();
    ambiguous["status"] = "manual".into();
    ambiguous["reason"] = "ambiguous_model_output".into();
    ambiguous["suggestedLocale"] = serde_json::Value::Null;
    ambiguous["observations"][0]["scoreMargin"] = 0.0.into();
    assert_eq!(
        request
            .decode_response(&serde_json::to_vec(&ambiguous).unwrap())
            .unwrap()
            .status,
        LidPreflightStatus::Manual
    );
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
        assert!(headers
            .to_ascii_lowercase()
            .contains("authorization: bearer lid-token"));
        write_json_response(&mut stream, 200, "OK", &response_body);
    });
    let client = BatchApiClient::new_authorized(
        bounded_client().unwrap(),
        &format!("http://{address}"),
        RequestAuthorization::fixed("lid-token"),
    )
    .unwrap();

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
        std::array::from_fn(|_| b"\x01\x00".repeat(96_000)),
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
        "componentId": "ambernet-batch-language-preflight",
        "runtime": {"pythonVersion": "3.12.13", "cpuOnly": true},
        "model": {
            "id": "nvidia/nemo/langid_ambernet",
            "revision": "1.12.0"
        },
        "transport": {
            "mediaType": "application/vnd.yap.lid-preflight.v1+octet-stream",
            "maximumBodyBytes": 1_048_576,
            "maximumManifestBytes": 32_768,
            "maximumResponseSeconds": 120
        },
        "policy": {
            "revision": "ambernet-stratified-five-region-v1",
            "sampleRateHz": 16_000,
            "channelCount": 1,
            "sampleWidthBytes": 2,
            "minimumSourceSamples": 480_000,
            "maximumWindows": 5,
            "maximumWindowSamples": 96_000,
            "minimumVoicedSamplesPerWindow": 51_200,
            "scoreSemantics": "mean-logit-log-softmax",
            "userConfirmationRequired": true
        }
    });
    AsrCapabilityCatalog::parse_bounded(&serde_json::to_vec(&value).unwrap()).unwrap()
}

fn valid_response() -> serde_json::Value {
    let observations = (0..5)
        .map(|index| {
            serde_json::json!({
                "index": index,
                "probeSha256": REGION_WAV_SHA256,
                "sourceStartSample": index * 96_000,
                "sourceEndSample": (index + 1) * 96_000,
                "voicedSamples": 96_000,
                "rawLabel": "en",
                "topScore": -0.1 - f64::from(index) / 100.0,
                "scoreMargin": 1.0,
                "mappedLocale": "en-US"
            })
        })
        .collect::<Vec<_>>();
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
            "id": "ambernet-batch-language-preflight",
            "runtime": {"pythonVersion": "3.12.13", "cpuOnly": true},
            "model": {
                "id": "nvidia/nemo/langid_ambernet",
                "revision": "1.12.0"
            },
            "policyRevision": "ambernet-stratified-five-region-v1",
            "scoreSemantics": "mean-logit-log-softmax"
        },
        "observations": observations
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
