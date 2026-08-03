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
fn obsolete_phase_derived_wire_alias_is_rejected() {
    for disposition in ["legacyPhase5Default", "legacyImplicitEnglishDefault"] {
        let legacy = serde_json::json!({
            "mode": "fixed",
            "languageBcp47": "en-US",
            "disposition": disposition
        });

        assert!(serde_json::from_value::<RecordingLanguageDecision>(legacy).is_err());
    }
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
