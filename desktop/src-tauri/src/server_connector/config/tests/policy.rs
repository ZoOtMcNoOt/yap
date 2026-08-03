use super::*;

#[test]
fn https_urls_normalize_to_an_origin_without_a_v1_suffix() {
    assert_eq!(
        validate_base_url("https://server.example:8443/v1/", false).unwrap(),
        "https://server.example:8443"
    );
    assert_eq!(
        validate_base_url("HTTPS://SERVER.EXAMPLE/", false).unwrap(),
        "https://server.example"
    );
    assert!(validate_base_url("https://server.example/api", false).is_err());
}

#[test]
fn loopback_http_accepts_ipv4_ipv6_and_localhost() {
    assert_eq!(
        validate_base_url("http://127.0.0.1:18765/v1", false).unwrap(),
        "http://127.0.0.1:18765"
    );
    assert_eq!(
        validate_base_url("http://[::1]:18765", false).unwrap(),
        "http://[::1]:18765"
    );
    assert_eq!(
        validate_base_url("http://localhost:18765/", false).unwrap(),
        "http://localhost:18765"
    );
}

#[test]
fn private_http_requires_the_explicit_process_override() {
    for raw in [
        "http://10.4.5.6:18765",
        "http://172.16.4.5:18765",
        "http://192.168.50.1:18765/v1",
    ] {
        assert!(validate_base_url(raw, false).is_err(), "accepted {raw}");
        assert!(validate_base_url(raw, true).is_ok(), "rejected {raw}");
    }
}

#[test]
fn public_http_is_rejected_even_when_private_http_is_allowed() {
    for raw in [
        "http://server.example:18765",
        "http://8.8.8.8:18765",
        "http://169.254.1.2:18765",
    ] {
        assert!(validate_base_url(raw, false).is_err(), "accepted {raw}");
        assert!(validate_base_url(raw, true).is_err(), "accepted {raw}");
    }
}

#[test]
fn credentials_queries_and_fragments_are_rejected() {
    for raw in [
        "https://user:secret@server.example",
        "https://server.example?token=secret",
        "https://server.example/#section",
    ] {
        assert!(validate_base_url(raw, false).is_err(), "accepted {raw}");
    }
}

#[test]
fn native_origin_approval_is_separate_and_exact() {
    let dir = temp_dir("origin-approval");
    let path = dir.join("server-origin-approval.json");

    assert!(!origin_is_approved_at(&path, "https://approved.example/v1", false).unwrap());
    assert_eq!(
        approve_origin_at(&path, "https://approved.example/v1", false).unwrap(),
        "https://approved.example"
    );
    assert!(origin_is_approved_at(&path, "https://approved.example", false).unwrap());
    assert!(!origin_is_approved_at(&path, "https://tampered.example", false).unwrap());

    let stored: serde_json::Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    assert_eq!(
        stored.get("origin").and_then(serde_json::Value::as_str),
        Some("https://approved.example")
    );
    assert_eq!(
        stored
            .get("schemaVersion")
            .and_then(serde_json::Value::as_u64),
        Some(1)
    );
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn malformed_or_noncanonical_origin_approval_fails_closed() {
    let dir = temp_dir("origin-approval-tamper");
    let path = dir.join("server-origin-approval.json");
    std::fs::write(&path, "{not-json").unwrap();
    assert!(origin_is_approved_at(&path, "https://approved.example", false).is_err());

    std::fs::write(
        &path,
        r#"{"schemaVersion":1,"origin":"https://approved.example/v1"}"#,
    )
    .unwrap();
    assert!(origin_is_approved_at(&path, "https://approved.example", false).is_err());
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn malformed_json_recovers_disabled_defaults() {
    let dir = temp_dir("malformed");
    let path = dir.join("server-settings.json");
    std::fs::write(&path, "{not-json").unwrap();

    assert_eq!(
        load_from_path(&path, false).unwrap(),
        ServerSettings::default()
    );

    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn obsolete_settings_schema_is_rejected_without_rewriting_it() {
    let dir = temp_dir("obsolete-schema");
    let path = dir.join("server-settings.json");
    let obsolete = br#"{"schemaVersion":1,"enabled":true,"baseUrl":"http://127.0.0.1:18765"}"#;
    std::fs::write(&path, obsolete).unwrap();

    assert!(matches!(
        load_from_path(&path, false),
        Err(ConfigError::IncompatibleSchema(1))
    ));
    assert!(matches!(
        save_to_path(&ServerSettings::default(), &path, false),
        Err(ConfigError::IncompatibleSchema(1))
    ));
    assert_eq!(std::fs::read(&path).unwrap(), obsolete);

    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn remote_https_requires_public_microsoft_entra_configuration() {
    let mut settings = ServerSettings {
        schema_version: CURRENT_SCHEMA_VERSION,
        enabled: true,
        base_url: Some("https://server.example/v1".into()),
        authentication: None,
    };
    assert!(matches!(
        normalize_settings(&settings, false),
        Err(ConfigError::Invalid(
            "Remote HTTPS servers require Microsoft Entra configuration."
        ))
    ));

    settings.authentication = Some(test_microsoft_entra_settings());
    let normalized = normalize_settings(&settings, false).unwrap();
    assert_eq!(
        normalized.base_url.as_deref(),
        Some("https://server.example")
    );
    assert_eq!(
        normalized.authentication,
        Some(test_microsoft_entra_settings())
    );
}

#[test]
fn bearer_configuration_never_allows_plaintext_private_transport() {
    let settings = ServerSettings {
        schema_version: CURRENT_SCHEMA_VERSION,
        enabled: true,
        base_url: Some("http://192.168.50.1:18765".into()),
        authentication: Some(test_microsoft_entra_settings()),
    };

    assert!(matches!(
        normalize_settings(&settings, true),
        Err(ConfigError::Invalid(
            "Authenticated server connections require HTTPS outside loopback."
        ))
    ));
}

#[test]
fn microsoft_entra_identifiers_and_api_scope_are_bounded_and_canonical() {
    let mut identity = test_microsoft_entra_settings();
    identity.tenant_id = " 11111111-AAAA-BBBB-CCCC-111111111111 ".into();
    let normalized = normalize_microsoft_entra_settings(&identity).unwrap();
    assert_eq!(normalized.tenant_id, "11111111-aaaa-bbbb-cccc-111111111111");

    identity.client_id = "not-a-client-id".into();
    assert!(normalize_microsoft_entra_settings(&identity).is_err());
    identity = test_microsoft_entra_settings();
    identity.api_scope = "https://graph.microsoft.com/User.Read".into();
    assert!(normalize_microsoft_entra_settings(&identity).is_err());
    identity.api_scope = format!(
        "api://{}/access_as_user",
        "a".repeat(MAX_IDENTITY_VALUE_BYTES)
    );
    assert!(normalize_microsoft_entra_settings(&identity).is_err());
}

#[test]
fn future_schema_is_preserved_and_reported_instead_of_downgraded() {
    let dir = temp_dir("future-schema");
    let path = dir.join("server-settings.json");
    let future = r#"{
  "schemaVersion": 3,
  "enabled": true,
  "baseUrl": "https://future.example",
  "futureField": "preserve-me"
}"#;
    std::fs::write(&path, future).unwrap();

    assert!(matches!(
        load_from_path(&path, false),
        Err(ConfigError::IncompatibleSchema(3))
    ));
    let replacement = ServerSettings {
        schema_version: CURRENT_SCHEMA_VERSION,
        enabled: false,
        base_url: None,
        authentication: None,
    };
    assert!(matches!(
        save_to_path(&replacement, &path, false),
        Err(ConfigError::IncompatibleSchema(3))
    ));
    assert_eq!(std::fs::read_to_string(&path).unwrap(), future);
    assert_eq!(partial_files(&dir), Vec::<String>::new());

    std::fs::remove_dir_all(dir).ok();
}
