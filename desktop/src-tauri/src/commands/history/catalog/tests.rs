use std::collections::HashSet;

use crate::{
    jobs::commands::{
        PublishedRemoteTranscriptCatalog, PublishedRemoteTranscriptSummary,
        TranscriptLanguageStatus, TranscriptResultSummary, TranscriptTimingStatus,
    },
    live::recordings::{RecoverableLiveSession, SavedLiveSession, SavedLiveSessionCatalog},
};

use super::*;

fn fixed_result_summary() -> TranscriptResultSummary {
    TranscriptResultSummary {
        language_bcp47: "en-US".into(),
        language_status: TranscriptLanguageStatus::Fixed,
        timing_status: TranscriptTimingStatus::Unavailable,
        active_language_correction_count: None,
        language_review_required_count: None,
    }
}

#[test]
fn catalog_combines_native_sources_with_explicit_provenance() {
    let catalog = build_history_catalog(
        SavedLiveSessionCatalog {
            sessions: vec![SavedLiveSession {
                session_id: "live-1".into(),
                name: "Live".into(),
                source_path: "live.wav".into(),
                output_path: "live.txt".into(),
                created_at_ms: 30,
                warning: None,
                capture_commit_path: Some("live.commit.json".into()),
                recovery_state: None,
            }],
            maintenance_warnings: vec!["shared warning".into()],
        },
        vec![RecoverableLiveSession {
            session_id: "recover-1".into(),
            name: "Recover".into(),
            audio_partial_path: Some("recover.wav.part".into()),
            journal_partial_path: None,
            reason: "Interrupted".into(),
            expires_at_ms: RECOVERY_WINDOW_MS + 20,
        }],
        PublishedRemoteTranscriptCatalog {
            sessions: vec![PublishedRemoteTranscriptSummary {
                session_id: "remote-1".into(),
                name: "Remote".into(),
                source_path: "source.wav".into(),
                output_path: "remote.txt".into(),
                created_at_ms: 10,
                speaker_transcript_available: true,
                result_summary: fixed_result_summary(),
                warning: None,
            }],
            maintenance_warnings: vec!["shared warning".into(), "remote warning".into()],
        },
    );

    assert_eq!(catalog.sessions.len(), 3);
    assert_eq!(catalog.sessions[0].origin, HistoryOrigin::Live);
    assert_eq!(
        catalog.sessions[1].recovery_state.as_deref(),
        Some("recoverable")
    );
    assert_eq!(catalog.sessions[1].created_at_ms, 20);
    assert_eq!(catalog.sessions[2].origin, HistoryOrigin::Remote);
    assert!(catalog.sessions[2].speaker_transcript_available);
    let encoded = serde_json::to_value(&catalog).unwrap();
    assert_eq!(encoded["sessions"][2]["speakerTranscriptAvailable"], true);
    assert!(encoded["sessions"][2].get("speakerTurns").is_none());
    assert_eq!(
        catalog.maintenance_warnings,
        ["shared warning", "remote warning"]
    );
}

#[test]
fn catalog_is_bounded_to_the_newest_native_sessions() {
    let remote_sessions = (0..=MAX_HISTORY_SESSIONS)
        .map(|index| PublishedRemoteTranscriptSummary {
            session_id: format!("remote-{index}"),
            name: format!("Remote {index}"),
            source_path: format!("source-{index}.wav"),
            output_path: format!("remote-{index}.txt"),
            created_at_ms: index as u64,
            speaker_transcript_available: false,
            result_summary: fixed_result_summary(),
            warning: None,
        })
        .collect();
    let catalog = build_history_catalog(
        SavedLiveSessionCatalog {
            sessions: Vec::new(),
            maintenance_warnings: Vec::new(),
        },
        Vec::new(),
        PublishedRemoteTranscriptCatalog {
            sessions: remote_sessions,
            maintenance_warnings: Vec::new(),
        },
    );

    assert_eq!(catalog.sessions.len(), MAX_HISTORY_SESSIONS);
    assert_eq!(
        catalog.sessions[0].created_at_ms,
        MAX_HISTORY_SESSIONS as u64
    );
    assert_eq!(catalog.sessions.last().unwrap().created_at_ms, 1);
}

#[test]
fn catalog_applies_native_visibility_before_the_history_window() {
    let remote_sessions = (0..=MAX_HISTORY_SESSIONS)
        .map(|index| PublishedRemoteTranscriptSummary {
            session_id: format!("remote-{index}"),
            name: format!("Remote {index}"),
            source_path: format!("source-{index}.wav"),
            output_path: format!("remote-{index}.txt"),
            created_at_ms: index as u64,
            speaker_transcript_available: false,
            result_summary: fixed_result_summary(),
            warning: None,
        })
        .collect();
    let raw = collect_history_catalog(
        SavedLiveSessionCatalog {
            sessions: Vec::new(),
            maintenance_warnings: Vec::new(),
        },
        Vec::new(),
        PublishedRemoteTranscriptCatalog {
            sessions: remote_sessions,
            maintenance_warnings: Vec::new(),
        },
    );
    let hidden = HashSet::from([NativeHistoryIdentity {
        origin: HistoryOrigin::Remote,
        session_id: format!("remote-{MAX_HISTORY_SESSIONS}"),
        output_path: format!("remote-{MAX_HISTORY_SESSIONS}.txt"),
    }]);

    let visible = project_history_catalog(raw, &hidden);

    assert_eq!(visible.sessions.len(), MAX_HISTORY_SESSIONS);
    assert_eq!(
        visible.sessions[0].created_at_ms,
        (MAX_HISTORY_SESSIONS - 1) as u64
    );
    assert_eq!(visible.sessions.last().unwrap().created_at_ms, 0);
}

#[test]
fn native_visibility_requires_the_exact_current_catalog_identity() {
    let raw = collect_history_catalog(
        SavedLiveSessionCatalog {
            sessions: Vec::new(),
            maintenance_warnings: Vec::new(),
        },
        Vec::new(),
        PublishedRemoteTranscriptCatalog {
            sessions: vec![PublishedRemoteTranscriptSummary {
                session_id: "remote-1".into(),
                name: "Remote".into(),
                source_path: "source.wav".into(),
                output_path: "remote.txt".into(),
                created_at_ms: 1,
                speaker_transcript_available: false,
                result_summary: fixed_result_summary(),
                warning: None,
            }],
            maintenance_warnings: Vec::new(),
        },
    );
    let current = raw.sessions[0].identity();
    assert_eq!(
        resolve_current_native_identity(&raw, &current),
        Some(current.clone())
    );

    let mut wrong_session = current.clone();
    wrong_session.session_id = "remote-2".into();
    assert_eq!(resolve_current_native_identity(&raw, &wrong_session), None);
    let mut wrong_path = current;
    wrong_path.output_path = "other.txt".into();
    assert_eq!(resolve_current_native_identity(&raw, &wrong_path), None);
}

#[test]
fn catalog_keeps_an_orphaned_recoverable_row_visible_by_name() {
    let catalog = build_history_catalog(
        SavedLiveSessionCatalog {
            sessions: Vec::new(),
            maintenance_warnings: Vec::new(),
        },
        vec![RecoverableLiveSession {
            session_id: "orphan".into(),
            name: "live-orphan".into(),
            audio_partial_path: None,
            journal_partial_path: None,
            reason: "Interrupted".into(),
            expires_at_ms: RECOVERY_WINDOW_MS,
        }],
        PublishedRemoteTranscriptCatalog {
            sessions: Vec::new(),
            maintenance_warnings: Vec::new(),
        },
    );

    assert_eq!(catalog.sessions[0].source_path, "live-orphan");
    assert_eq!(catalog.sessions[0].output_path, "live-orphan");
}
