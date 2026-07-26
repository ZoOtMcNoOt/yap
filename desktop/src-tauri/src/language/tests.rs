use super::RecordingLanguageDecision;

#[test]
fn legacy_implicit_default_uses_a_functional_wire_name() {
    let decision = RecordingLanguageDecision::legacy_implicit_english_default();

    let serialized = serde_json::to_value(&decision).unwrap();

    assert_eq!(
        serialized["disposition"],
        serde_json::Value::String("legacyImplicitEnglishDefault".into())
    );
}

#[test]
fn legacy_wire_alias_remains_backward_readable() {
    let legacy = serde_json::json!({
        "mode": "fixed",
        "languageBcp47": "en-US",
        "disposition": "legacyPhase5Default"
    });

    let decoded: RecordingLanguageDecision = serde_json::from_value(legacy).unwrap();

    assert_eq!(
        decoded,
        RecordingLanguageDecision::legacy_implicit_english_default()
    );
}
