use std::collections::HashSet;

use crate::{
    jobs::commands::PublishedRemoteTranscriptCatalog,
    live::recordings::{RecoverableLiveSession, SavedLiveSessionCatalog},
};

use super::{
    HistoryCatalog, HistoryCatalogSession, HistoryOrigin, NativeHistoryIdentity,
    MAX_HISTORY_SESSIONS, RECOVERY_WINDOW_MS,
};

pub(super) fn resolve_current_native_identity(
    catalog: &HistoryCatalog,
    requested: &NativeHistoryIdentity,
) -> Option<NativeHistoryIdentity> {
    catalog
        .sessions
        .iter()
        .map(HistoryCatalogSession::identity)
        .find(|current| current == requested)
}

#[cfg(test)]
fn build_history_catalog(
    live: SavedLiveSessionCatalog,
    recoverable: Vec<RecoverableLiveSession>,
    remote: PublishedRemoteTranscriptCatalog,
) -> HistoryCatalog {
    project_history_catalog(
        collect_history_catalog(live, recoverable, remote),
        &HashSet::new(),
    )
}

pub(super) fn collect_history_catalog(
    live: SavedLiveSessionCatalog,
    recoverable: Vec<RecoverableLiveSession>,
    remote: PublishedRemoteTranscriptCatalog,
) -> HistoryCatalog {
    let mut sessions = live
        .sessions
        .into_iter()
        .map(|session| HistoryCatalogSession {
            capture_commit_path: session.capture_commit_path,
            created_at_ms: session.created_at_ms,
            name: session.name,
            origin: HistoryOrigin::Live,
            output_path: session.output_path,
            recovery_state: session.recovery_state,
            result_summary: None,
            speaker_transcript_available: false,
            session_id: session.session_id,
            source_path: session.source_path,
            warning: session.warning,
        })
        .chain(recoverable.into_iter().map(|session| {
            let artifact_path = session
                .audio_partial_path
                .or(session.journal_partial_path)
                .unwrap_or_else(|| session.name.clone());
            HistoryCatalogSession {
                capture_commit_path: None,
                created_at_ms: session.expires_at_ms.saturating_sub(RECOVERY_WINDOW_MS),
                name: session.name,
                origin: HistoryOrigin::Live,
                output_path: artifact_path.clone(),
                recovery_state: Some("recoverable".into()),
                result_summary: None,
                speaker_transcript_available: false,
                session_id: session.session_id,
                source_path: artifact_path,
                warning: Some(session.reason),
            }
        }))
        .chain(
            remote
                .sessions
                .into_iter()
                .map(|session| HistoryCatalogSession {
                    capture_commit_path: None,
                    created_at_ms: session.created_at_ms,
                    name: session.name,
                    origin: HistoryOrigin::Remote,
                    output_path: session.output_path,
                    recovery_state: None,
                    result_summary: Some(session.result_summary),
                    speaker_transcript_available: session.speaker_transcript_available,
                    session_id: session.session_id,
                    source_path: session.source_path,
                    warning: session.warning,
                }),
        )
        .collect::<Vec<_>>();
    sessions.sort_by(|left, right| {
        right
            .created_at_ms
            .cmp(&left.created_at_ms)
            .then_with(|| left.session_id.cmp(&right.session_id))
            .then_with(|| left.origin.cmp(&right.origin))
    });

    let mut seen_warnings = HashSet::new();
    let maintenance_warnings = live
        .maintenance_warnings
        .into_iter()
        .chain(remote.maintenance_warnings)
        .filter(|warning| seen_warnings.insert(warning.clone()))
        .collect();
    HistoryCatalog {
        maintenance_warnings,
        sessions,
    }
}

pub(super) fn project_history_catalog(
    mut catalog: HistoryCatalog,
    hidden: &HashSet<NativeHistoryIdentity>,
) -> HistoryCatalog {
    catalog
        .sessions
        .retain(|session| !hidden.contains(&session.identity()));
    catalog.sessions.truncate(MAX_HISTORY_SESSIONS);
    catalog
}

#[cfg(test)]
mod tests;
