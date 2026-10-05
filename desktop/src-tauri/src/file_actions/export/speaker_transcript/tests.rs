use super::*;
use crate::jobs::commands::PublishedSpeakerTranscriptTurn;

fn source() -> PublishedSpeakerTranscript {
    PublishedSpeakerTranscript {
        session_id: "s-export".into(),
        source_result_sha256: "a".repeat(64),
        turns: vec![
            PublishedSpeakerTranscriptTurn {
                turn_id: "turn-000001".into(),
                speaker_id: Some("speaker-1".into()),
                start_ms: 17,
                end_ms: 1900,
                text: "Café — 日本語\n\"original\"".into(),
                overlap_group_id: Some("overlap-1".into()),
            },
            PublishedSpeakerTranscriptTurn {
                turn_id: "turn-000002".into(),
                speaker_id: None,
                start_ms: 800,
                end_ms: 2010,
                text: "Unknown speaker".into(),
                overlap_group_id: Some("overlap-1".into()),
            },
        ],
    }
}
struct Fixture {
    root: std::path::PathBuf,
    data: std::path::PathBuf,
    output: std::path::PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "yap-speaker-export-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let data = root.join("data");
        let output = root.join("exports");
        std::fs::create_dir_all(&data).unwrap();
        std::fs::create_dir(&output).unwrap();
        Self { root, data, output }
    }
    fn save(
        &self,
        path: &Path,
        current: impl FnOnce() -> Result<PublishedSpeakerTranscript, String>,
    ) -> Result<SpeakerTranscriptExport, String> {
        let original = source();
        export_selected(&original, &serialize(&original)?, path, &self.data, current)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.root).ok();
    }
}

#[test]
fn timed_export_serializes_exact_complete_source_and_unknown_overlap_turns() {
    let fixture = Fixture::new();
    let target = fixture.output.join("turns");
    let receipt = fixture.save(&target, || Ok(source())).unwrap();
    let path = fixture.output.join("turns.json");
    assert_eq!(
        receipt,
        SpeakerTranscriptExport::Saved {
            path: path.display().to_string(),
            session_id: source().session_id,
            source_result_sha256: source().source_result_sha256
        }
    );
    let json: serde_json::Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    let mut expected = serde_json::to_value(source()).unwrap();
    expected["schemaVersion"] = 1.into();
    assert_eq!(json, expected);
    assert_eq!(json["turns"][1]["speakerId"], serde_json::Value::Null);
    assert_eq!(json["turns"][0]["startMs"], 17);
}
#[test]
fn timed_export_rechecks_every_turn_and_source_identity_before_creation() {
    let fixture = Fixture::new();
    let target = fixture.output.join("turns.json");
    for field in 0..5 {
        let mut changed = source();
        match field {
            0 => changed.session_id = "foreign".into(),
            1 => changed.source_result_sha256 = "b".repeat(64),
            2 => changed.turns[0].text = "substituted".into(),
            3 => changed.turns[0].start_ms += 1,
            _ => changed.turns[0].speaker_id = None,
        }
        assert!(fixture
            .save(&target, || Ok(changed))
            .unwrap_err()
            .contains("changed"));
        assert!(!target.exists());
    }
    assert!(fixture
        .save(&target, || Err(SOURCE_UNAVAILABLE.into()))
        .is_err());
    assert_eq!(std::fs::read_dir(&fixture.output).unwrap().count(), 0);
}
#[test]
fn timed_export_refuses_existing_internal_relative_and_wrong_extension_destinations() {
    let fixture = Fixture::new();
    let target = fixture.output.join("turns.json");
    std::fs::write(&target, "existing work").unwrap();
    assert!(fixture
        .save(&target, || Ok(source()))
        .unwrap_err()
        .contains("already exists"));
    assert_eq!(std::fs::read_to_string(target).unwrap(), "existing work");
    for path in [
        fixture.data.join("turns.json"),
        fixture.output.join("turns.txt"),
        "relative.json".into(),
    ] {
        assert!(fixture.save(&path, || Ok(source())).is_err());
    }
    assert_eq!(std::fs::read_dir(&fixture.data).unwrap().count(), 0);
}
#[test]
fn timed_export_caps_escaped_output_without_truncation_or_publication() {
    let mut original = source();
    original.turns[0].text = "\u{1}".repeat(MAX_EXPORT_BYTES / 5);
    assert_eq!(serialize(&original).unwrap_err(), OUTPUT_TOO_LARGE);
    let mut output = BoundedOutput(Vec::new());
    output.write_all(&vec![b'x'; MAX_EXPORT_BYTES]).unwrap();
    assert!(output.write_all(b"x").is_err());
    assert_eq!(output.0.len(), MAX_EXPORT_BYTES);
}
#[cfg(unix)]
#[test]
fn timed_export_preserves_symlink_destinations_and_refuses_internal_aliases() {
    let fixture = Fixture::new();
    let retained = fixture.data.join("source.json");
    std::fs::write(&retained, "source").unwrap();
    let link = fixture.output.join("turns.json");
    std::os::unix::fs::symlink(&retained, &link).unwrap();
    assert!(fixture.save(&link, || Ok(source())).is_err());
    let alias = fixture.output.join("alias");
    std::os::unix::fs::symlink(&fixture.data, &alias).unwrap();
    assert!(fixture
        .save(&alias.join("turns.json"), || Ok(source()))
        .is_err());
    assert_eq!(std::fs::read_to_string(retained).unwrap(), "source");
}
#[cfg(unix)]
#[test]
fn timed_export_retains_destination_ownership_and_reports_write_uncertainty() {
    let fixture = Fixture::new();
    let target = fixture.output.join("turns.json");
    let error = fixture
        .save(&target, || {
            std::fs::rename(&fixture.output, fixture.root.join("retained")).unwrap();
            std::os::unix::fs::symlink(&fixture.data, &fixture.output).unwrap();
            Ok(source())
        })
        .unwrap_err();
    assert!(error.contains("could not be confirmed"));
    assert!(!fixture.data.join("turns.json").exists());
    assert_eq!(
        std::fs::read_dir(fixture.root.join("retained"))
            .unwrap()
            .count(),
        0
    );
}
