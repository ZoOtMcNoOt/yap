use std::collections::HashSet;

use crate::{
    jobs::commands::CompletedRemoteTranscriptCatalog,
    live::recordings::{RecoverableLiveSession, SavedLiveSessionCatalog},
};

use super::{
    HistoryCatalog, HistoryCatalogSession, HistoryOrigin, NativeHistoryIdentity,
    MAX_HISTORY_PATH_CHARS, MAX_HISTORY_SESSIONS, RECOVERY_WINDOW_MS,
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

pub(super) fn select_hidden_path_migration(
    catalog: &HistoryCatalog,
    output_paths: Vec<String>,
) -> (Vec<NativeHistoryIdentity>, Vec<String>) {
    let mut identities = Vec::new();
    let mut seen_identities = HashSet::new();
    let mut migrated_output_paths = Vec::new();
    let mut seen_requested = HashSet::new();
    for output_path in output_paths {
        if output_path.is_empty() || output_path.chars().count() > MAX_HISTORY_PATH_CHARS {
            continue;
        }
        let requested_identity = history_path_identity(&output_path);
        if !seen_requested.insert(requested_identity.clone()) {
            continue;
        }
        let matching = catalog
            .sessions
            .iter()
            .filter(|session| history_path_identity(&session.output_path) == requested_identity);
        let before = identities.len();
        for identity in matching.map(HistoryCatalogSession::identity) {
            if seen_identities.insert(identity.clone()) {
                identities.push(identity);
            }
        }
        if identities.len() > before {
            migrated_output_paths.push(output_path);
        }
    }
    (identities, migrated_output_paths)
}

#[cfg(test)]
fn build_history_catalog(
    live: SavedLiveSessionCatalog,
    recoverable: Vec<RecoverableLiveSession>,
    remote: CompletedRemoteTranscriptCatalog,
) -> HistoryCatalog {
    project_history_catalog(
        collect_history_catalog(live, recoverable, remote),
        &HashSet::new(),
    )
}

pub(super) fn collect_history_catalog(
    live: SavedLiveSessionCatalog,
    recoverable: Vec<RecoverableLiveSession>,
    remote: CompletedRemoteTranscriptCatalog,
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

fn history_path_identity(path: &str) -> String {
    let is_windows = path
        .as_bytes()
        .get(1)
        .is_some_and(|separator| *separator == b':')
        || path.starts_with("\\\\")
        || path.starts_with("//");
    if !is_windows {
        return path.to_owned();
    }

    let mut normalized = path.replace('/', "\\");
    if normalized
        .get(..8)
        .is_some_and(|prefix| prefix.eq_ignore_ascii_case("\\\\?\\UNC\\"))
    {
        normalized = format!("\\\\{}", &normalized[8..]);
    } else if normalized
        .get(..4)
        .is_some_and(|prefix| prefix.eq_ignore_ascii_case("\\\\?\\"))
    {
        normalized = normalized[4..].to_owned();
    }
    let unc = normalized.starts_with("\\\\");
    let root_depth = if unc { 2 } else { 1 };
    let mut resolved = Vec::new();
    for segment in normalized.split('\\').filter(|segment| !segment.is_empty()) {
        match segment {
            "." => {}
            ".." if resolved.len() > root_depth => {
                resolved.pop();
            }
            ".." => {}
            _ => resolved.push(segment),
        }
    }
    format!("{}{}", if unc { "\\\\" } else { "" }, resolved.join("\\")).to_lowercase()
}

#[cfg(test)]
mod tests;
