use super::RecordingLanguageDecision;

fn rust_sources(root: &std::path::Path, sources: &mut Vec<std::path::PathBuf>) {
    for entry in std::fs::read_dir(root).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            rust_sources(&path, sources);
        } else if path.extension().is_some_and(|extension| extension == "rs") {
            sources.push(path);
        }
    }
}

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

#[test]
fn language_owners_do_not_depend_on_stt_adapters() {
    let source_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let mut sources = vec![source_root.join("language.rs")];
    rust_sources(&source_root.join("language"), &mut sources);
    rust_sources(&source_root.join("language_preferences"), &mut sources);
    let forbidden_dependency = ["crate", "::stt"].concat();

    let violations = sources
        .into_iter()
        .filter_map(|path| {
            let text = std::fs::read_to_string(&path).unwrap();
            text.contains(&forbidden_dependency).then(|| {
                path.strip_prefix(&source_root)
                    .unwrap()
                    .display()
                    .to_string()
            })
        })
        .collect::<Vec<_>>();

    assert_eq!(
        violations,
        Vec::<String>::new(),
        "language owners imported a concrete STT adapter"
    );
}
