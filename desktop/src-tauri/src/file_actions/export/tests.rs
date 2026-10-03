use super::*;
use crate::audio::{recording::StreamingRecording, session::SessionId};
use std::path::PathBuf;

struct Fixture {
    root: PathBuf,
    data: PathBuf,
    output: PathBuf,
    source: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        static SEQUENCE: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "yap-export-{}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos(),
            SEQUENCE.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
        ));
        let data = root.join("data");
        let output = root.join("exports");
        std::fs::create_dir_all(&data).unwrap();
        std::fs::create_dir(&output).unwrap();
        let session = SessionId::new("s-export").unwrap();
        let mut recording = StreamingRecording::create(&data, session.clone()).unwrap();
        recording.append_pcm16(&[1, 0]).unwrap();
        let capture = recording.finalize().unwrap();
        crate::live::recordings::save_finalized_capture_to_dir_for_test(
            &data,
            "Reviewed café — 日本語\nKeep 10 mg, not 100 mg.",
            capture,
        )
        .unwrap();
        let source = data.join(format!("live-{session}.txt"));
        Self {
            root,
            data,
            output,
            source,
        }
    }

    fn read(&self) -> Result<String, String> {
        super::super::transcripts::read_text_file_at_from_dir(
            self.source.to_string_lossy().into_owned(),
            &self.data,
        )
    }

    fn export(&self, target: &Path) -> Result<TranscriptExport, String> {
        export_selected_transcript(&self.read()?, target, &self.data, || self.read())
    }

    fn assert_no_temporary_files(&self) {
        assert!(std::fs::read_dir(&self.output).unwrap().all(|entry| {
            !entry
                .unwrap()
                .file_name()
                .to_string_lossy()
                .ends_with(".part")
        }));
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.root).ok();
    }
}

#[test]
fn original_and_accepted_exports_share_one_worker_permit() {
    let permit = export_permit().unwrap();
    assert!(export_permit().unwrap_err().contains("current export"));
    drop(permit);
    assert!(export_permit().is_ok());
}

#[test]
fn export_preserves_utf8_bytes_and_the_committed_original() {
    let fixture = Fixture::new();
    let original = std::fs::read(&fixture.source).unwrap();
    let target = fixture.output.join("meeting.txt");
    assert_eq!(
        fixture.export(&target).unwrap(),
        TranscriptExport::Saved {
            path: target
                .canonicalize()
                .unwrap()
                .to_string_lossy()
                .into_owned(),
        }
    );
    assert_eq!(std::fs::read(target).unwrap(), original);
    assert_eq!(std::fs::read(&fixture.source).unwrap(), original);
    fixture.assert_no_temporary_files();
}

#[test]
fn export_supplies_txt_extension_without_changing_the_selected_folder() {
    let fixture = Fixture::new();
    fixture.export(&fixture.output.join("meeting")).unwrap();
    assert_eq!(
        std::fs::read(fixture.output.join("meeting.txt")).unwrap(),
        std::fs::read(&fixture.source).unwrap()
    );
}

#[test]
fn export_preserves_existing_files_and_does_not_remove_unrelated_part_files() {
    let fixture = Fixture::new();
    let target = fixture.output.join("meeting.txt");
    std::fs::write(&target, "existing work").unwrap();
    let unrelated = fixture.output.join("meeting.txt.part");
    std::fs::write(&unrelated, "unrelated work").unwrap();
    assert!(fixture
        .export(&target)
        .unwrap_err()
        .contains("already exists"));
    assert_eq!(std::fs::read_to_string(&target).unwrap(), "existing work");
    assert_eq!(
        std::fs::read_to_string(&unrelated).unwrap(),
        "unrelated work"
    );
    assert_eq!(std::fs::read_dir(&fixture.output).unwrap().count(), 2);
}

#[test]
fn export_rejects_internal_data_and_invalid_destinations() {
    let fixture = Fixture::new();
    for target in [fixture.data.join("export.txt"), fixture.source.clone()] {
        assert!(fixture
            .export(&target)
            .unwrap_err()
            .contains("internal data"));
    }
    assert!(fixture.export(Path::new("relative.txt")).is_err());
    assert!(fixture
        .export(&fixture.output.join("meeting.json"))
        .is_err());
    assert!(fixture
        .export(&fixture.root.join("missing/meeting.txt"))
        .is_err());
    fixture.assert_no_temporary_files();
}

#[test]
fn export_revalidates_source_after_the_destination_is_chosen() {
    let fixture = Fixture::new();
    let original = fixture.read().unwrap();
    let target = fixture.output.join("meeting.txt");
    std::fs::write(&fixture.source, "substituted text").unwrap();
    assert!(
        export_selected_transcript(&original, &target, &fixture.data, || fixture.read()).is_err()
    );
    assert!(!target.exists());
    fixture.assert_no_temporary_files();
}

#[test]
fn export_rejects_a_missing_or_unowned_source_without_creating_a_file() {
    let fixture = Fixture::new();
    let original = fixture.read().unwrap();
    let target = fixture.output.join("meeting.txt");
    std::fs::remove_file(&fixture.source).unwrap();
    assert!(
        export_selected_transcript(&original, &target, &fixture.data, || fixture.read()).is_err()
    );
    std::fs::write(&fixture.source, &original).unwrap();
    let unowned = fixture.output.join("unowned.txt");
    std::fs::write(&unowned, &original).unwrap();
    assert!(
        export_selected_transcript(&original, &target, &fixture.data, || {
            super::super::transcripts::read_text_file_at_from_dir(
                unowned.to_string_lossy().into_owned(),
                &fixture.data,
            )
        })
        .is_err()
    );
    assert!(!target.exists());
}

#[test]
fn export_does_not_publish_an_outdated_validated_snapshot() {
    let fixture = Fixture::new();
    let target = fixture.output.join("meeting.txt");
    let original = fixture.read().unwrap();
    assert!(
        export_selected_transcript(&original, &target, &fixture.data, || Ok(
            "new revision".into()
        ))
        .unwrap_err()
        .contains("changed")
    );
    assert!(!target.exists());
}

#[test]
fn export_write_failure_preserves_the_destination_and_cleans_staging() {
    let fixture = Fixture::new();
    let target = fixture.output.join("folder.txt");
    std::fs::create_dir(&target).unwrap();
    assert!(fixture.export(&target).is_err());
    assert!(target.is_dir());
    fixture.assert_no_temporary_files();
}

#[cfg(unix)]
#[test]
fn changed_destination_reports_unconfirmed_without_losing_source_or_replacement() {
    let fixture = Fixture::new();
    let original = fixture.read().unwrap();
    let target = fixture.output.join("meeting.txt");
    let error = export_selected_transcript(&original, &target, &fixture.data, || {
        std::fs::remove_dir(&fixture.output).unwrap();
        std::fs::write(&fixture.output, "retained replacement").unwrap();
        Ok(original.clone())
    })
    .unwrap_err();
    assert!(error.contains("could not be confirmed"));
    assert!(error.contains("file may already have been saved"));
    assert_eq!(fixture.read().unwrap(), original);
    assert_eq!(
        std::fs::read_to_string(&fixture.output).unwrap(),
        "retained replacement"
    );
    assert!(!target.exists());
}

#[test]
fn export_byte_limit_rejects_oversized_text_before_publication() {
    let fixture = Fixture::new();
    let target = fixture.output.join("meeting.txt");
    let text = "x".repeat(super::super::transcripts::MAX_TRANSCRIPT_READ_BYTES as usize + 1);
    assert!(
        export_selected_transcript(&text, &target, &fixture.data, || Ok(text.clone())).is_err()
    );
    assert!(!target.exists());
}

#[test]
fn concurrent_exports_to_one_destination_never_replace_the_winner() {
    let fixture = Fixture::new();
    let target = fixture.output.join("meeting.txt");
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let threads: Vec<_> = ["first", "second"]
        .into_iter()
        .map(|text| {
            let target = target.clone();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                let destination = crate::atomic_text::NewFileDestination::open(&target)?;
                crate::atomic_text::write_new(&destination, text)
            })
        })
        .collect();
    let results: Vec<_> = threads
        .into_iter()
        .map(|thread| thread.join().unwrap())
        .collect();
    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    assert!(matches!(
        std::fs::read_to_string(target).unwrap().as_str(),
        "first" | "second"
    ));
    fixture.assert_no_temporary_files();
}

#[cfg(unix)]
#[test]
fn export_rejects_destination_symlinks_and_internal_folder_aliases() {
    let fixture = Fixture::new();
    let alias = fixture.output.join("alias");
    std::os::unix::fs::symlink(&fixture.data, &alias).unwrap();
    assert!(fixture
        .export(&alias.join("export.txt"))
        .unwrap_err()
        .contains("internal data"));
    let target = fixture.output.join("linked.txt");
    std::os::unix::fs::symlink(&fixture.source, &target).unwrap();
    assert!(fixture.export(&target).is_err());
    assert!(fixture.read().is_ok());
    fixture.assert_no_temporary_files();
}

#[cfg(unix)]
#[test]
fn export_cannot_follow_a_substituted_destination_into_internal_data() {
    let fixture = Fixture::new();
    let original = fixture.read().unwrap();
    let target = fixture.output.join("redirected.txt");
    let result = export_selected_transcript(&original, &target, &fixture.data, || {
        std::fs::rename(&fixture.output, fixture.root.join("retained-export-folder")).unwrap();
        std::os::unix::fs::symlink(&fixture.data, &fixture.output).unwrap();
        Ok(original.clone())
    });
    assert!(
        !fixture.data.join("redirected.txt").exists(),
        "destination substitution redirected publication into internal data: {result:?}"
    );
    assert!(result.is_err());
    assert_eq!(fixture.read().unwrap(), original);
}

#[cfg(unix)]
#[test]
fn export_creates_private_files() {
    use std::os::unix::fs::PermissionsExt;
    let fixture = Fixture::new();
    let target = fixture.output.join("meeting.txt");
    fixture.export(&target).unwrap();
    assert_eq!(
        std::fs::metadata(target).unwrap().permissions().mode() & 0o777,
        0o600
    );
}

#[cfg(unix)]
#[test]
fn export_rejects_a_replaced_ancestor_without_writing_into_its_substitute() {
    let fixture = Fixture::new();
    let original = fixture.read().unwrap();
    std::fs::create_dir(fixture.output.join("nested")).unwrap();
    std::fs::create_dir(fixture.data.join("nested")).unwrap();
    let target = fixture.output.join("nested/review.txt");
    let result = export_selected_transcript(&original, &target, &fixture.data, || {
        std::fs::rename(&fixture.output, fixture.root.join("retained")).unwrap();
        std::os::unix::fs::symlink(&fixture.data, &fixture.output).unwrap();
        Ok(original.clone())
    });
    assert!(result.unwrap_err().contains("could not be confirmed"));
    assert!(!fixture.data.join("nested/review.txt").exists());
    assert_eq!(
        std::fs::read_dir(fixture.root.join("retained/nested"))
            .unwrap()
            .count(),
        0
    );
    assert_eq!(fixture.read().unwrap(), original);
}

#[cfg(windows)]
#[test]
fn export_directory_leases_block_parent_and_ancestor_moves_but_allow_publication() {
    let fixture = Fixture::new();
    let original = fixture.read().unwrap();
    let parent = fixture.output.join("nested");
    std::fs::create_dir(&parent).unwrap();
    let target = parent.join("review.txt");
    let result = export_selected_transcript(&original, &target, &fixture.data, || {
        assert!(std::fs::rename(&parent, fixture.output.join("moved-parent")).is_err());
        assert!(std::fs::remove_dir(&parent).is_err());
        assert!(std::fs::rename(&fixture.output, fixture.root.join("moved-ancestor")).is_err());
        Ok(original.clone())
    });
    assert!(matches!(result, Ok(TranscriptExport::Saved { .. })));
    assert_eq!(std::fs::read_to_string(&target).unwrap(), original);
    assert_eq!(fixture.read().unwrap(), original);
    fixture.assert_no_temporary_files();
    // The blocking export released every lease before returning.
    std::fs::rename(&parent, fixture.output.join("moved-parent")).unwrap();
}
