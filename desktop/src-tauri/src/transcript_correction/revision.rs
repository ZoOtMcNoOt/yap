use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    sync::Mutex,
};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use time::{format_description::well_known::Rfc3339, OffsetDateTime};

use super::{
    read_trusted_transcript_correction_source, TranscriptCorrectionSourceKind,
    TrustedTranscriptCorrectionSource,
};

const REVISION_SCHEMA_VERSION: u16 = 1;
const MAXIMUM_REVISIONS: usize = 64;
const MAXIMUM_REVISION_BYTES: usize = 192 * 1024;
const MAXIMUM_CORRECTED_CHARACTERS: usize = 32_768;
const REMOTE_CORRECTION_DIRECTORY: &str = "transcript-corrections";
static CORRECTION_PUBLICATION: Mutex<()> = Mutex::new(());

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum TranscriptCorrectionAuthority {
    UserAcceptedModelCorrection,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TranscriptCorrectionRevision {
    schema_version: u16,
    revision: u64,
    authority: TranscriptCorrectionAuthority,
    created_at_utc: String,
    request_id: String,
    source_revision_sha256: String,
    source_sha256: String,
    terminology_snapshot_sha256: String,
    previous_correction_sha256: Option<String>,
    corrected_sha256: String,
    corrected_text: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct PublishedTranscriptCorrection {
    pub(crate) request_id: String,
    pub(crate) revision: u64,
    pub(crate) source_revision_sha256: String,
    pub(crate) source_sha256: String,
    pub(crate) terminology_snapshot_sha256: String,
    pub(crate) corrected_sha256: String,
    pub(crate) corrected_text: String,
    pub(crate) revision_path: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct RecoveredTranscriptCorrection {
    pub(crate) schema_version: u16,
    pub(crate) output_path: String,
    pub(crate) source_revision_sha256: String,
    pub(crate) source_sha256: String,
    pub(crate) accepted_revision: Option<PublishedTranscriptCorrection>,
}

pub(crate) fn read_accepted_transcript_correction(
    output_path: &Path,
) -> Result<RecoveredTranscriptCorrection, String> {
    read_accepted_transcript_correction_with_reader(
        output_path,
        read_trusted_transcript_correction_source,
    )
}

fn read_accepted_transcript_correction_with_reader(
    output_path: &Path,
    mut read_source: impl FnMut(&Path) -> Result<TrustedTranscriptCorrectionSource, String>,
) -> Result<RecoveredTranscriptCorrection, String> {
    let _publication = CORRECTION_PUBLICATION
        .lock()
        .map_err(|_| "Saved transcript corrections are unavailable.".to_string())?;
    let source = read_source(output_path)?;
    let owner = existing_correction_owner(&source)?;
    let revisions = match owner {
        Some(owner) => load_revision_chain(&source, &owner)?,
        None => Vec::new(),
    };
    if let Some(latest) = revisions.last() {
        validate_revision(
            &latest.revision,
            revisions.len() as u64,
            revisions.iter().rev().nth(1),
            Some(&source),
        )?;
    }
    if read_source(output_path)? != source {
        return Err("The original transcript changed while reading its saved corrections.".into());
    }
    Ok(RecoveredTranscriptCorrection {
        schema_version: 1,
        output_path: source.output_path.display().to_string(),
        source_revision_sha256: source.source_revision_sha256.clone(),
        source_sha256: sha256_text(&source.text),
        accepted_revision: revisions.last().map(project),
    })
}

fn existing_correction_owner(
    source: &TrustedTranscriptCorrectionSource,
) -> Result<Option<PathBuf>, String> {
    if source.kind == TranscriptCorrectionSourceKind::Live {
        return correction_owner(source).map(Some);
    }
    let owner = source
        .output_path
        .parent()
        .and_then(Path::parent)
        .ok_or_else(|| "The server transcript has no correction owner.".to_string())?
        .join(REMOTE_CORRECTION_DIRECTORY);
    match fs::symlink_metadata(&owner) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(_) => Err("Failed to inspect saved transcript corrections.".into()),
        Ok(metadata) => {
            require_private_directory(&metadata)?;
            Ok(Some(owner))
        }
    }
}

struct LoadedRevision {
    revision: TranscriptCorrectionRevision,
    sha256: String,
    path: PathBuf,
}

pub(crate) fn publish_transcript_correction_revision(
    source: &TrustedTranscriptCorrectionSource,
    request_id: &str,
    terminology_snapshot_sha256: &str,
    corrected_text: &str,
) -> Result<PublishedTranscriptCorrection, String> {
    publish_transcript_correction_revision_with_reader(
        source,
        request_id,
        terminology_snapshot_sha256,
        corrected_text,
        read_trusted_transcript_correction_source,
    )
}

pub(crate) fn live_transcript_correction_artifacts_for_deletion(
    output_path: &Path,
    source_revision_sha256: String,
    source_text: String,
) -> Result<Vec<(String, String)>, String> {
    let _publication = CORRECTION_PUBLICATION
        .lock()
        .map_err(|_| "Transcript correction publication is unavailable.".to_string())?;
    let source = TrustedTranscriptCorrectionSource {
        kind: TranscriptCorrectionSourceKind::Live,
        output_path: output_path.to_path_buf(),
        source_revision_sha256,
        text: source_text,
        segments: Vec::new(),
    };
    let owner = correction_owner(&source)?;
    cleanup_stale_revision_staging(source.kind, &source.output_path, &owner)?;
    load_revision_chain(&source, &owner).map(|revisions| {
        revisions
            .into_iter()
            .map(|loaded| {
                (
                    loaded
                        .path
                        .file_name()
                        .and_then(|value| value.to_str())
                        .expect("validated live correction has a UTF-8 name")
                        .to_owned(),
                    loaded.sha256,
                )
            })
            .collect()
    })
}

fn publish_transcript_correction_revision_with_reader<ReadSource>(
    source: &TrustedTranscriptCorrectionSource,
    request_id: &str,
    terminology_snapshot_sha256: &str,
    corrected_text: &str,
    mut read_source: ReadSource,
) -> Result<PublishedTranscriptCorrection, String>
where
    ReadSource: FnMut(&Path) -> Result<TrustedTranscriptCorrectionSource, String>,
{
    let _publication = CORRECTION_PUBLICATION
        .lock()
        .map_err(|_| "Transcript correction publication is unavailable.".to_string())?;
    validate_identifier(request_id, "request identity")?;
    if !valid_sha256(terminology_snapshot_sha256) {
        return Err("The transcript correction terminology snapshot is invalid.".into());
    }
    validate_corrected_text(&source.text, corrected_text)?;
    require_current_source(source, &mut read_source)?;
    let owner = correction_owner(source)?;
    cleanup_stale_revision_staging(source.kind, &source.output_path, &owner)?;
    let revisions = load_revision_chain(source, &owner)?;
    let corrected_sha256 = sha256_text(corrected_text);
    if let Some(existing) = revisions
        .iter()
        .find(|existing| existing.revision.request_id == request_id)
    {
        if existing.revision.source_revision_sha256 != source.source_revision_sha256
            || existing.revision.source_sha256 != sha256_text(&source.text)
            || existing.revision.terminology_snapshot_sha256 != terminology_snapshot_sha256
            || existing.revision.corrected_sha256 != corrected_sha256
            || existing.revision.corrected_text != corrected_text
        {
            return Err(
                "The transcript correction request was already committed differently.".into(),
            );
        }
        return Ok(project(existing));
    }
    let revision_number = u64::try_from(revisions.len())
        .ok()
        .and_then(|value| value.checked_add(1))
        .ok_or_else(|| "Transcript correction revision overflowed.".to_string())?;
    if revision_number > MAXIMUM_REVISIONS as u64 {
        return Err(format!(
            "A transcript accepts at most {MAXIMUM_REVISIONS} correction revisions."
        ));
    }
    let revision = TranscriptCorrectionRevision {
        schema_version: REVISION_SCHEMA_VERSION,
        revision: revision_number,
        authority: TranscriptCorrectionAuthority::UserAcceptedModelCorrection,
        created_at_utc: OffsetDateTime::now_utc()
            .format(&Rfc3339)
            .map_err(|_| "Failed to timestamp transcript correction revision.".to_string())?,
        request_id: request_id.to_owned(),
        source_revision_sha256: source.source_revision_sha256.clone(),
        source_sha256: sha256_text(&source.text),
        terminology_snapshot_sha256: terminology_snapshot_sha256.to_owned(),
        previous_correction_sha256: revisions.last().map(|loaded| loaded.sha256.clone()),
        corrected_sha256,
        corrected_text: corrected_text.to_owned(),
    };
    validate_revision(&revision, revision_number, revisions.last(), Some(source))?;
    let bytes = serde_json::to_vec(&revision)
        .map_err(|_| "Failed to encode transcript correction revision.".to_string())?;
    if bytes.len() > MAXIMUM_REVISION_BYTES {
        return Err("The transcript correction revision is too large.".into());
    }
    let destination = owner.join(revision_file_name(
        source.kind,
        &source.output_path,
        revision_number,
    ));
    publish_new_private_file(&destination, &bytes)?;
    require_current_source(source, &mut read_source)?;
    let persisted = load_revision_chain(source, &owner)?;
    let latest = persisted
        .last()
        .filter(|loaded| loaded.revision == revision)
        .ok_or_else(|| "The transcript correction revision could not be verified.".to_string())?;
    Ok(project(latest))
}

#[cfg(test)]
pub(crate) fn publish_transcript_correction_revision_for_test(
    source: &TrustedTranscriptCorrectionSource,
    request_id: &str,
    terminology_snapshot_sha256: &str,
    corrected_text: &str,
) -> Result<PublishedTranscriptCorrection, String> {
    publish_transcript_correction_revision_with_reader(
        source,
        request_id,
        terminology_snapshot_sha256,
        corrected_text,
        |_: &Path| Ok(source.clone()),
    )
}

fn require_current_source(
    source: &TrustedTranscriptCorrectionSource,
    read_source: &mut impl FnMut(&Path) -> Result<TrustedTranscriptCorrectionSource, String>,
) -> Result<(), String> {
    let current = read_source(&source.output_path)?;
    if &current != source {
        return Err("The raw transcript changed before the correction was saved.".into());
    }
    Ok(())
}

fn correction_owner(source: &TrustedTranscriptCorrectionSource) -> Result<PathBuf, String> {
    match source.kind {
        TranscriptCorrectionSourceKind::Live => source
            .output_path
            .parent()
            .map(Path::to_path_buf)
            .ok_or_else(|| "The live transcript has no correction owner.".to_string()),
        TranscriptCorrectionSourceKind::Remote => {
            let job_root = source
                .output_path
                .parent()
                .and_then(Path::parent)
                .ok_or_else(|| "The server transcript has no correction owner.".to_string())?;
            prepare_private_directory(&job_root.join(REMOTE_CORRECTION_DIRECTORY))
        }
    }
}

fn load_revision_chain(
    source: &TrustedTranscriptCorrectionSource,
    owner: &Path,
) -> Result<Vec<LoadedRevision>, String> {
    let paths = revision_paths(source.kind, &source.output_path, owner)?;
    let mut result = Vec::with_capacity(paths.len());
    for (index, path) in paths.into_iter().enumerate() {
        let expected_revision = index as u64 + 1;
        let metadata = fs::symlink_metadata(&path)
            .map_err(|_| "Failed to inspect transcript correction revision.".to_string())?;
        if !metadata.is_file()
            || crate::bounded_file::metadata_is_link_or_reparse(&metadata)
            || metadata.len() == 0
            || metadata.len() > MAXIMUM_REVISION_BYTES as u64
        {
            return Err("A transcript correction revision is not bounded.".into());
        }
        let admission = crate::audio::recording::admit_regular_artifact(&path)?;
        let (text, sha256) = admission.read_and_hash()?;
        let revision: TranscriptCorrectionRevision = serde_json::from_str(&text)
            .map_err(|_| "A transcript correction revision is incompatible.".to_string())?;
        validate_revision(&revision, expected_revision, result.last(), None)?;
        result.push(LoadedRevision {
            revision,
            sha256,
            path,
        });
    }
    Ok(result)
}

fn validate_revision(
    revision: &TranscriptCorrectionRevision,
    expected_revision: u64,
    previous: Option<&LoadedRevision>,
    current_source: Option<&TrustedTranscriptCorrectionSource>,
) -> Result<(), String> {
    let timestamp_valid = revision.created_at_utc.ends_with('Z')
        && revision.created_at_utc.len() <= 64
        && OffsetDateTime::parse(&revision.created_at_utc, &Rfc3339).is_ok();
    if revision.schema_version != REVISION_SCHEMA_VERSION
        || revision.revision != expected_revision
        || revision.authority != TranscriptCorrectionAuthority::UserAcceptedModelCorrection
        || !timestamp_valid
        || validate_identifier(&revision.request_id, "request identity").is_err()
        || !valid_sha256(&revision.source_revision_sha256)
        || !valid_sha256(&revision.source_sha256)
        || !valid_sha256(&revision.terminology_snapshot_sha256)
        || revision.previous_correction_sha256 != previous.map(|loaded| loaded.sha256.clone())
        || revision.corrected_sha256 != sha256_text(&revision.corrected_text)
        || revision.corrected_sha256 == revision.source_sha256
        || validate_corrected_text_shape(&revision.corrected_text).is_err()
        || current_source.is_some_and(|source| {
            revision.source_revision_sha256 != source.source_revision_sha256
                || revision.source_sha256 != sha256_text(&source.text)
                || revision.corrected_text == source.text
        })
    {
        return Err("A transcript correction revision conflicts with its source history.".into());
    }
    Ok(())
}

fn revision_paths(
    kind: TranscriptCorrectionSourceKind,
    output_path: &Path,
    owner: &Path,
) -> Result<Vec<PathBuf>, String> {
    let mut paths = Vec::new();
    for entry in fs::read_dir(owner)
        .map_err(|error| format!("Failed to read transcript correction history: {error}"))?
    {
        let entry = entry
            .map_err(|error| format!("Failed to inspect transcript correction history: {error}"))?;
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| "A transcript correction artifact name is invalid.".to_string())?;
        let parsed = parse_revision_file_name(kind, output_path, &name);
        if let Some(revision) = parsed {
            paths.push((revision, entry.path()));
            if paths.len() > MAXIMUM_REVISIONS {
                return Err("Transcript correction history is too large.".into());
            }
            continue;
        }
        if valid_revision_staging_file_name(kind, output_path, &name) {
            return Err("Transcript correction history contains stale staging.".into());
        }
        if kind == TranscriptCorrectionSourceKind::Live
            && live_revision_prefix(output_path).is_some_and(|prefix| {
                name.starts_with(&prefix) || name.starts_with(&format!(".{prefix}"))
            })
        {
            return Err("Transcript correction history contains an invalid revision name.".into());
        }
        if kind == TranscriptCorrectionSourceKind::Remote {
            return Err("Transcript correction history contains an unexpected artifact.".into());
        }
    }
    if paths.len() > MAXIMUM_REVISIONS {
        return Err("Transcript correction history is too large.".into());
    }
    paths.sort_by_key(|(revision, _)| *revision);
    if paths
        .iter()
        .enumerate()
        .any(|(index, (revision, _))| *revision != index as u64 + 1)
    {
        return Err("Transcript correction revisions are not a complete sequence.".into());
    }
    Ok(paths.into_iter().map(|(_, path)| path).collect())
}

fn revision_file_name(
    kind: TranscriptCorrectionSourceKind,
    output_path: &Path,
    revision: u64,
) -> String {
    match kind {
        TranscriptCorrectionSourceKind::Live => format!(
            "{}{revision:020}.json",
            live_revision_prefix(output_path).expect("validated live transcript has a file stem")
        ),
        TranscriptCorrectionSourceKind::Remote => format!("correction-{revision:020}.json"),
    }
}

fn parse_revision_file_name(
    kind: TranscriptCorrectionSourceKind,
    output_path: &Path,
    name: &str,
) -> Option<u64> {
    let value = match kind {
        TranscriptCorrectionSourceKind::Remote => {
            name.strip_prefix("correction-")?.strip_suffix(".json")?
        }
        TranscriptCorrectionSourceKind::Live => name
            .strip_prefix(&live_revision_prefix(output_path)?)?
            .strip_suffix(".json")?,
    };
    (value.len() == 20 && value.bytes().all(|byte| byte.is_ascii_digit()))
        .then(|| value.parse::<u64>().ok())
        .flatten()
        .filter(|revision| *revision > 0)
}

fn live_revision_prefix(output_path: &Path) -> Option<String> {
    let stem = output_path.file_stem()?.to_str()?;
    Some(format!("{stem}.transcript-correction.r"))
}

fn validate_corrected_text(source_text: &str, corrected_text: &str) -> Result<(), String> {
    validate_corrected_text_shape(corrected_text)?;
    if corrected_text == source_text {
        return Err("The accepted transcript correction is invalid.".into());
    }
    Ok(())
}

fn validate_corrected_text_shape(corrected_text: &str) -> Result<(), String> {
    if corrected_text.is_empty()
        || corrected_text.contains('\0')
        || corrected_text.chars().count() > MAXIMUM_CORRECTED_CHARACTERS
    {
        return Err("The accepted transcript correction is invalid.".into());
    }
    Ok(())
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
}

fn validate_identifier(value: &str, label: &str) -> Result<(), String> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
    {
        return Err(format!("The transcript correction {label} is invalid."));
    }
    Ok(())
}

fn project(loaded: &LoadedRevision) -> PublishedTranscriptCorrection {
    PublishedTranscriptCorrection {
        request_id: loaded.revision.request_id.clone(),
        revision: loaded.revision.revision,
        source_revision_sha256: loaded.revision.source_revision_sha256.clone(),
        source_sha256: loaded.revision.source_sha256.clone(),
        terminology_snapshot_sha256: loaded.revision.terminology_snapshot_sha256.clone(),
        corrected_sha256: loaded.revision.corrected_sha256.clone(),
        corrected_text: loaded.revision.corrected_text.clone(),
        revision_path: loaded.path.display().to_string(),
    }
}

fn sha256_text(value: &str) -> String {
    Sha256::digest(value.as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn prepare_private_directory(path: &Path) -> Result<PathBuf, String> {
    match create_private_directory(path) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(error) => {
            return Err(format!(
                "Failed to create transcript correction history: {error}"
            ))
        }
    }
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("Failed to inspect transcript correction history: {error}"))?;
    require_private_directory(&metadata)?;
    Ok(path.to_path_buf())
}

fn require_private_directory(metadata: &fs::Metadata) -> Result<(), String> {
    if !metadata.is_dir()
        || crate::bounded_file::metadata_is_link_or_reparse(metadata)
        || !metadata_is_private(metadata)
    {
        return Err("Transcript corrections are not stored in a private Yap directory.".into());
    }
    Ok(())
}

#[cfg(unix)]
fn create_private_directory(path: &Path) -> std::io::Result<()> {
    use std::os::unix::fs::DirBuilderExt;
    let mut builder = fs::DirBuilder::new();
    builder.mode(0o700).create(path)
}

#[cfg(not(unix))]
fn create_private_directory(path: &Path) -> std::io::Result<()> {
    fs::create_dir(path)
}

#[cfg(unix)]
fn metadata_is_private(metadata: &fs::Metadata) -> bool {
    use std::os::unix::fs::PermissionsExt;
    metadata.permissions().mode() & 0o077 == 0
}

#[cfg(not(unix))]
fn metadata_is_private(_metadata: &fs::Metadata) -> bool {
    true
}

fn publish_new_private_file(destination: &Path, bytes: &[u8]) -> Result<(), String> {
    let file_name = destination
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "Transcript correction destination is invalid.".to_string())?;
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    for attempt in 0..32_u8 {
        let staging = destination.with_file_name(format!(
            ".{file_name}.staging-{}-{nonce}-{attempt}",
            std::process::id()
        ));
        let mut file = match open_private_create_new(&staging) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(format!(
                    "Failed to reserve transcript correction staging: {error}"
                ))
            }
        };
        let result = (|| {
            file.write_all(bytes)
                .and_then(|_| file.flush())
                .and_then(|_| file.sync_all())
                .map_err(|error| format!("Failed to write transcript correction: {error}"))?;
            crate::atomic_file::rename_same_directory_no_replace(&staging, destination)
                .map_err(|error| format!("Failed to publish transcript correction: {error}"))?;
            crate::atomic_file::sync_parent_directory(destination)
                .map_err(|error| format!("Failed to sync transcript correction: {error}"))?;
            let admission = crate::audio::recording::admit_regular_artifact(destination)?;
            let (persisted, _) = admission.read_and_hash()?;
            if persisted.as_bytes() != bytes {
                return Err("Published transcript correction differs from its revision.".into());
            }
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_file(&staging);
        }
        return result;
    }
    Err("Failed to allocate transcript correction staging.".into())
}

#[cfg(unix)]
fn open_private_create_new(path: &Path) -> std::io::Result<File> {
    use std::os::unix::fs::OpenOptionsExt;
    OpenOptions::new()
        .create_new(true)
        .write(true)
        .read(true)
        .mode(0o600)
        .open(path)
}

#[cfg(not(unix))]
fn open_private_create_new(path: &Path) -> std::io::Result<File> {
    OpenOptions::new()
        .create_new(true)
        .write(true)
        .read(true)
        .open(path)
}

fn cleanup_stale_revision_staging(
    kind: TranscriptCorrectionSourceKind,
    output_path: &Path,
    owner: &Path,
) -> Result<(), String> {
    let mut removed_path = None;
    for entry in fs::read_dir(owner)
        .map_err(|error| format!("Failed to read transcript correction history: {error}"))?
    {
        let entry = entry
            .map_err(|error| format!("Failed to inspect transcript correction history: {error}"))?;
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| "A transcript correction artifact name is invalid.".to_string())?;
        if !valid_revision_staging_file_name(kind, output_path, &name) {
            continue;
        }
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path)
            .map_err(|_| "Failed to inspect transcript correction staging.".to_string())?;
        if !metadata.is_file() || crate::bounded_file::metadata_is_link_or_reparse(&metadata) {
            return Err("Transcript correction staging is not a regular file.".into());
        }
        fs::remove_file(&path)
            .map_err(|error| format!("Failed to remove transcript correction staging: {error}"))?;
        removed_path = Some(path);
    }
    if let Some(path) = removed_path {
        crate::atomic_file::sync_parent_directory(&path).map_err(|error| {
            format!("Failed to sync transcript correction staging cleanup: {error}")
        })?;
    }
    Ok(())
}

fn valid_revision_staging_file_name(
    kind: TranscriptCorrectionSourceKind,
    output_path: &Path,
    name: &str,
) -> bool {
    let Some(value) = name.strip_prefix('.') else {
        return false;
    };
    let Some((destination, suffix)) = value.split_once(".staging-") else {
        return false;
    };
    if parse_revision_file_name(kind, output_path, destination).is_none() {
        return false;
    }
    let parts = suffix.split('-').collect::<Vec<_>>();
    parts.len() == 3
        && parts
            .iter()
            .all(|part| !part.is_empty() && part.bytes().all(|byte| byte.is_ascii_digit()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::file_actions::export::accepted_correction::{
        export_selected_accepted_correction, require_displayed_revision, AcceptedCorrectionExport,
    };

    struct ExportFixture {
        root: PathBuf,
        data: PathBuf,
        destination: PathBuf,
        source: TrustedTranscriptCorrectionSource,
    }

    impl ExportFixture {
        fn new(label: &str) -> Self {
            let root = test_directory(label);
            let data = root.join("data");
            let destination = root.join("exports");
            fs::create_dir(&data).unwrap();
            fs::create_dir(&destination).unwrap();
            let session = crate::audio::session::SessionId::new("s-accepted-export").unwrap();
            let mut recording =
                crate::audio::recording::StreamingRecording::create(&data, session.clone())
                    .unwrap();
            recording.append_pcm16(&[1, 0]).unwrap();
            crate::live::recordings::save_finalized_capture_to_dir_for_test(
                &data,
                "Dose is twenty five mg.",
                recording.finalize().unwrap(),
            )
            .unwrap();
            let source = super::super::source::read_live_source_from_dir(
                &data.join(format!("live-{session}.txt")),
                &data,
            )
            .unwrap();
            Self {
                root,
                data,
                destination,
                source,
            }
        }

        fn export(
            &self,
            accepted: &RecoveredTranscriptCorrection,
            target: &Path,
        ) -> Result<AcceptedCorrectionExport, String> {
            export_selected_accepted_correction(accepted, target, &self.data, || self.recover())
        }

        fn recover(&self) -> Result<RecoveredTranscriptCorrection, String> {
            read_accepted_transcript_correction_with_reader(&self.source.output_path, |path| {
                super::super::source::read_live_source_from_dir(path, &self.data)
            })
        }
    }

    impl Drop for ExportFixture {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.root).ok();
        }
    }

    #[test]
    fn accepted_export_preserves_exact_utf8_original_and_complete_history() {
        let fixture = ExportFixture::new("export-accepted-utf8");
        let first = accept(&fixture.source, "first", "Dose: 25 mg.");
        let text = "Reviewed café — 日本語\nKeep 10 mg, not 100 mg.\n";
        let last = accept(&fixture.source, "last", text);
        let original = fs::read(&fixture.source.output_path).unwrap();
        let first_bytes = fs::read(&first.revision_path).unwrap();
        let last_bytes = fs::read(&last.revision_path).unwrap();
        let accepted =
            require_displayed_revision(fixture.recover().unwrap(), 2, &last.corrected_sha256)
                .unwrap();
        let target = fixture.destination.join("accepted");
        let receipt = fixture.export(&accepted, &target).unwrap();
        let target = target.with_extension("txt");
        assert_eq!(
            receipt,
            AcceptedCorrectionExport::Saved {
                path: target.display().to_string(),
                revision: 2,
                corrected_sha256: last.corrected_sha256.clone()
            }
        );
        assert_eq!(fs::read(&target).unwrap(), text.as_bytes());
        assert_eq!(fs::read(&fixture.source.output_path).unwrap(), original);
        assert_eq!(fs::read(&first.revision_path).unwrap(), first_bytes);
        assert_eq!(fs::read(&last.revision_path).unwrap(), last_bytes);
        assert_eq!(fs::read_dir(&fixture.destination).unwrap().count(), 1);
        assert_eq!(
            serde_json::to_value(receipt).unwrap()["correctedSha256"],
            last.corrected_sha256
        );
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(&target).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
    }

    #[test]
    fn accepted_export_refuses_missing_or_mismatched_displayed_revision() {
        let fixture = ExportFixture::new("export-accepted-claims");
        assert!(
            require_displayed_revision(fixture.recover().unwrap(), 1, &"a".repeat(64))
                .unwrap_err()
                .contains("No accepted")
        );
        let saved = accept(&fixture.source, "saved", "Dose: 25 mg.");
        let accepted = fixture.recover().unwrap();
        for (revision, hash) in [
            (0, saved.corrected_sha256.clone()),
            (2, saved.corrected_sha256),
            (1, "wrong".into()),
        ] {
            assert!(
                require_displayed_revision(accepted.clone(), revision, &hash)
                    .unwrap_err()
                    .contains("Refresh")
            );
        }
        assert_eq!(fs::read_dir(&fixture.destination).unwrap().count(), 0);
    }

    #[test]
    fn accepted_export_rechecks_revision_identity_even_when_corrected_text_is_unchanged() {
        let fixture = ExportFixture::new("export-accepted-advance");
        let text = "Dose: 25 mg.";
        let first = accept(&fixture.source, "first", text);
        let accepted = fixture.recover().unwrap();
        let last = accept(&fixture.source, "last", text);
        assert_eq!(first.corrected_sha256, last.corrected_sha256);
        let target = fixture.destination.join("accepted.txt");
        assert!(fixture
            .export(&accepted, &target)
            .unwrap_err()
            .contains("changed while choosing"));
        assert!(!target.exists());
        assert_eq!(fixture.recover().unwrap().accepted_revision.unwrap(), last);
    }

    #[test]
    fn accepted_export_rejects_changed_source_proof_and_missing_source_after_selection() {
        let fixture = ExportFixture::new("export-accepted-source");
        let original = fs::read(&fixture.source.output_path).unwrap();
        accept(&fixture.source, "saved", "Dose: 25 mg.");
        let accepted = fixture.recover().unwrap();
        let target = fixture.destination.join("accepted.txt");
        for changed in [
            TrustedTranscriptCorrectionSource {
                source_revision_sha256: "f".repeat(64),
                ..fixture.source.clone()
            },
            TrustedTranscriptCorrectionSource {
                text: "A new raw transcript.".into(),
                ..fixture.source.clone()
            },
        ] {
            assert!(
                export_selected_accepted_correction(&accepted, &target, &fixture.data, || recover(
                    &changed
                ))
                .is_err()
            );
        }
        assert!(
            export_selected_accepted_correction(&accepted, &target, &fixture.data, || Err(
                "The source was removed.".into()
            ))
            .is_err()
        );
        assert!(!target.exists());
        assert_eq!(fs::read(&fixture.source.output_path).unwrap(), original);
        fs::remove_file(&fixture.source.output_path).unwrap();
        assert!(fixture.export(&accepted, &target).is_err());
        assert!(!target.exists());
    }

    #[test]
    fn accepted_export_refuses_corrupt_or_missing_history_without_cleanup() {
        let fixture = ExportFixture::new("export-accepted-history");
        let saved = accept(&fixture.source, "saved", "Dose: 25 mg.");
        let accepted = fixture.recover().unwrap();
        let bytes = fs::read(&saved.revision_path).unwrap();
        let target = fixture.destination.join("accepted.txt");
        fs::write(&saved.revision_path, "corrupt history").unwrap();
        assert!(fixture.export(&accepted, &target).is_err());
        assert_eq!(
            fs::read_to_string(&saved.revision_path).unwrap(),
            "corrupt history"
        );
        fs::remove_file(&saved.revision_path).unwrap();
        assert!(fixture.export(&accepted, &target).is_err());
        fs::write(&saved.revision_path, &bytes).unwrap();
        let staging = fixture.data.join(format!(
            ".{}.staging-1-2-3",
            Path::new(&saved.revision_path)
                .file_name()
                .unwrap()
                .to_str()
                .unwrap()
        ));
        fs::write(&staging, "preserved staging").unwrap();
        assert!(fixture.export(&accepted, &target).is_err());
        assert_eq!(fs::read_to_string(staging).unwrap(), "preserved staging");
        assert_eq!(fs::read(&saved.revision_path).unwrap(), bytes);
        assert!(!target.exists());
    }

    #[test]
    fn accepted_export_retains_existing_files_and_protects_internal_destinations() {
        let fixture = ExportFixture::new("export-accepted-destination");
        let saved = accept(&fixture.source, "saved", "Dose: 25 mg.");
        let accepted = fixture.recover().unwrap();
        let target = fixture.destination.join("accepted.txt");
        let unrelated = fixture.destination.join("accepted.txt.part");
        fs::write(&target, "existing work").unwrap();
        fs::write(&unrelated, "unrelated work").unwrap();
        assert!(fixture
            .export(&accepted, &target)
            .unwrap_err()
            .contains("already exists"));
        for internal in [
            fixture.data.join("accepted.txt"),
            fixture.source.output_path.clone(),
            PathBuf::from(&saved.revision_path),
        ] {
            assert!(fixture.export(&accepted, &internal).is_err());
        }
        assert_eq!(fs::read_to_string(target).unwrap(), "existing work");
        assert_eq!(fs::read_to_string(unrelated).unwrap(), "unrelated work");
        assert_eq!(fs::read_dir(&fixture.destination).unwrap().count(), 2);
        assert_eq!(fixture.recover().unwrap(), accepted);
    }

    fn source(directory: &Path) -> TrustedTranscriptCorrectionSource {
        let output_path = directory.join("live-s-correction-test.txt");
        fs::write(&output_path, "Dose is twenty five mg.\n").unwrap();
        TrustedTranscriptCorrectionSource {
            kind: TranscriptCorrectionSourceKind::Live,
            output_path,
            source_revision_sha256: "a".repeat(64),
            text: "Dose is twenty five mg.\n".into(),
            segments: Vec::new(),
        }
    }

    fn test_directory(label: &str) -> PathBuf {
        let directory = std::env::temp_dir().join(format!(
            "yap-transcript-correction-{label}-{}",
            std::process::id()
        ));
        fs::remove_dir_all(&directory).ok();
        fs::create_dir_all(&directory).unwrap();
        directory
    }

    fn recover(
        source: &TrustedTranscriptCorrectionSource,
    ) -> Result<RecoveredTranscriptCorrection, String> {
        read_accepted_transcript_correction_with_reader(&source.output_path, |_| Ok(source.clone()))
    }

    fn accept(
        source: &TrustedTranscriptCorrectionSource,
        id: &str,
        text: &str,
    ) -> PublishedTranscriptCorrection {
        publish_transcript_correction_revision_with_reader(
            source,
            id,
            &"b".repeat(64),
            text,
            |_| Ok(source.clone()),
        )
        .unwrap()
    }

    #[test]
    fn recovery_reads_latest_accepted_revision_after_reopening_without_mutating_original_or_history(
    ) {
        let directory = test_directory("recovery-reopen");
        let source = source(&directory);
        assert!(recover(&source).unwrap().accepted_revision.is_none());
        let first = accept(&source, "accepted-first", "Dose is 25 mg.");
        let second = accept(&source, "accepted-second", "Dose: 25 mg.");
        let first_bytes = fs::read(&first.revision_path).unwrap();
        let second_bytes = fs::read(&second.revision_path).unwrap();
        let loaded = recover(&source).unwrap();
        assert_eq!(loaded.output_path, source.output_path.display().to_string());
        assert_eq!(loaded.source_sha256, sha256_text(&source.text));
        assert_eq!(loaded.accepted_revision, Some(second.clone()));
        assert_eq!(recover(&source).unwrap(), loaded);
        assert_eq!(
            fs::read_to_string(&source.output_path).unwrap(),
            source.text
        );
        assert_eq!(fs::read(&first.revision_path).unwrap(), first_bytes);
        assert_eq!(fs::read(&second.revision_path).unwrap(), second_bytes);
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn recovery_isolates_live_sources_and_refuses_a_latest_revision_for_different_source_proof() {
        let directory = test_directory("recovery-source-proof");
        let source = source(&directory);
        let accepted = accept(&source, "accepted-first", "Dose is 25 mg.");
        let mut other = source.clone();
        other.output_path = directory.join("live-other.txt");
        fs::write(&other.output_path, &other.text).unwrap();
        assert!(recover(&other).unwrap().accepted_revision.is_none());
        for changed in [
            TrustedTranscriptCorrectionSource {
                source_revision_sha256: "c".repeat(64),
                ..source.clone()
            },
            TrustedTranscriptCorrectionSource {
                text: "A different original.".into(),
                ..source.clone()
            },
        ] {
            assert!(recover(&changed)
                .unwrap_err()
                .contains("conflicts with its source history"));
        }
        assert!(Path::new(&accepted.revision_path).exists());
        assert_eq!(
            fs::read_to_string(&source.output_path).unwrap(),
            source.text
        );
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn recovery_rechecks_the_trusted_source_after_loading_its_history() {
        let directory = test_directory("recovery-source-race");
        let source = source(&directory);
        accept(&source, "accepted-first", "Dose is 25 mg.");
        let mut reads = 0;
        let result = read_accepted_transcript_correction_with_reader(&source.output_path, |_| {
            reads += 1;
            Ok(if reads == 1 {
                source.clone()
            } else {
                TrustedTranscriptCorrectionSource {
                    source_revision_sha256: "c".repeat(64),
                    ..source.clone()
                }
            })
        });
        assert!(result.unwrap_err().contains("changed while reading"));
        assert_eq!(fs::read_dir(&directory).unwrap().count(), 2);
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn remote_recovery_does_not_create_missing_history_and_preserves_an_existing_private_history() {
        let directory = test_directory("recovery-remote");
        let mut source = source(&directory);
        let outputs = directory.join("outputs");
        fs::create_dir(&outputs).unwrap();
        source.kind = TranscriptCorrectionSourceKind::Remote;
        source.output_path = outputs.join("transcript.json");
        fs::write(&source.output_path, &source.text).unwrap();
        let history = directory.join(REMOTE_CORRECTION_DIRECTORY);
        assert!(recover(&source).unwrap().accepted_revision.is_none());
        assert!(!history.exists());
        let accepted = accept(&source, "accepted-remote", "Dose is 25 mg.");
        assert_eq!(recover(&source).unwrap().accepted_revision, Some(accepted));
        assert_eq!(fs::read_dir(&history).unwrap().count(), 1);
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn recovery_refuses_corrupt_or_incomplete_history_without_deleting_any_artifact() {
        let directory = test_directory("recovery-corrupt");
        let source = source(&directory);
        let first = accept(&source, "accepted-first", "Dose is 25 mg.");
        let second = accept(&source, "accepted-second", "Dose: 25 mg.");
        let bytes = fs::read(&first.revision_path).unwrap();
        fs::write(&first.revision_path, b"{}").unwrap();
        assert!(recover(&source).is_err());
        assert_eq!(fs::read(&first.revision_path).unwrap(), b"{}");
        fs::write(&first.revision_path, &bytes).unwrap();
        fs::remove_file(&first.revision_path).unwrap();
        assert!(recover(&source).unwrap_err().contains("complete sequence"));
        assert!(Path::new(&second.revision_path).exists());
        assert_eq!(
            fs::read_to_string(&source.output_path).unwrap(),
            source.text
        );
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn recovery_refuses_staging_excessive_files_and_excessive_history_without_cleanup() {
        let directory = test_directory("recovery-bounds");
        let source = source(&directory);
        let first = accept(&source, "accepted-first", "Dose is 25 mg.");
        let staging = directory.join(format!(
            ".{}.staging-1-2-0",
            revision_file_name(source.kind, &source.output_path, 2)
        ));
        fs::write(&staging, b"pending").unwrap();
        assert!(recover(&source).is_err());
        assert_eq!(fs::read(&staging).unwrap(), b"pending");
        fs::remove_file(staging).unwrap();
        let bytes = fs::read(&first.revision_path).unwrap();
        fs::write(&first.revision_path, vec![b'x'; MAXIMUM_REVISION_BYTES + 1]).unwrap();
        assert!(recover(&source).unwrap_err().contains("not bounded"));
        fs::write(&first.revision_path, &bytes).unwrap();
        for index in 2..=65 {
            fs::write(
                directory.join(revision_file_name(source.kind, &source.output_path, index)),
                &bytes,
            )
            .unwrap();
        }
        assert!(recover(&source)
            .unwrap_err()
            .contains("history is too large"));
        assert_eq!(fs::read_dir(&directory).unwrap().count(), 66);
        fs::remove_dir_all(directory).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn recovery_refuses_linked_revisions_and_linked_or_public_remote_history() {
        use std::os::unix::{fs::symlink, fs::PermissionsExt};
        let directory = test_directory("recovery-links");
        let mut source = source(&directory);
        let first = accept(&source, "accepted-first", "Dose is 25 mg.");
        fs::remove_file(&first.revision_path).unwrap();
        symlink(&source.output_path, &first.revision_path).unwrap();
        assert!(recover(&source).unwrap_err().contains("not bounded"));
        assert!(fs::symlink_metadata(&first.revision_path)
            .unwrap()
            .file_type()
            .is_symlink());
        let outputs = directory.join("outputs");
        fs::create_dir(&outputs).unwrap();
        source.kind = TranscriptCorrectionSourceKind::Remote;
        source.output_path = outputs.join("transcript.json");
        let history = directory.join(REMOTE_CORRECTION_DIRECTORY);
        symlink(&directory, &history).unwrap();
        assert!(recover(&source)
            .unwrap_err()
            .contains("private Yap directory"));
        fs::remove_file(&history).unwrap();
        fs::create_dir(&history).unwrap();
        fs::set_permissions(&history, fs::Permissions::from_mode(0o755)).unwrap();
        assert!(recover(&source)
            .unwrap_err()
            .contains("private Yap directory"));
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn accepted_corrections_are_immutable_hash_chained_and_idempotent() {
        let directory = test_directory("revision-chain");
        let source = source(&directory);
        let first = publish_transcript_correction_revision_with_reader(
            &source,
            "agent-first",
            &"c".repeat(64),
            "Dose is 25 mg.\n",
            |_: &Path| Ok(source.clone()),
        )
        .unwrap();
        assert_eq!(first.revision, 1);
        assert_eq!(first.terminology_snapshot_sha256, "c".repeat(64));
        assert_eq!(
            fs::read_to_string(&source.output_path).unwrap(),
            source.text
        );
        let first_bytes = fs::read(&first.revision_path).unwrap();
        let first_hash = Sha256::digest(&first_bytes)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let repeated = publish_transcript_correction_revision_with_reader(
            &source,
            "agent-first",
            &"c".repeat(64),
            "Dose is 25 mg.\n",
            |_| Ok(source.clone()),
        )
        .unwrap();
        assert_eq!(repeated, first);

        let second = publish_transcript_correction_revision_with_reader(
            &source,
            "agent-second",
            &"c".repeat(64),
            "The dose is 25 mg.\n",
            |_| Ok(source.clone()),
        )
        .unwrap();
        assert_eq!(second.revision, 2);
        let second_revision: TranscriptCorrectionRevision =
            serde_json::from_slice(&fs::read(&second.revision_path).unwrap()).unwrap();
        assert_eq!(second_revision.previous_correction_sha256, Some(first_hash));
        assert_eq!(
            fs::read_dir(&directory)
                .unwrap()
                .filter_map(Result::ok)
                .filter(|entry| entry
                    .file_name()
                    .to_string_lossy()
                    .contains("transcript-correction.r"))
                .count(),
            2
        );
        fs::remove_dir_all(directory).ok();
    }

    #[test]
    fn source_change_and_revision_tamper_fail_closed() {
        let directory = test_directory("source-tamper");
        let source = source(&directory);
        let changed = TrustedTranscriptCorrectionSource {
            text: "Dose changed.\n".into(),
            ..source.clone()
        };
        assert!(publish_transcript_correction_revision_with_reader(
            &source,
            "agent-stale",
            &"c".repeat(64),
            "Dose is 25 mg.\n",
            |_| Ok(changed.clone()),
        )
        .is_err());

        let first = publish_transcript_correction_revision_with_reader(
            &source,
            "agent-first",
            &"c".repeat(64),
            "Dose is 25 mg.\n",
            |_| Ok(source.clone()),
        )
        .unwrap();
        fs::write(&first.revision_path, b"{}").unwrap();
        assert!(publish_transcript_correction_revision_with_reader(
            &source,
            "agent-second",
            &"c".repeat(64),
            "The dose is 25 mg.\n",
            |_| Ok(source.clone()),
        )
        .is_err());
        fs::remove_dir_all(directory).ok();
    }

    #[test]
    fn owned_stale_staging_is_removed_before_publication_and_deletion() {
        let directory = test_directory("stale-staging");
        let source = source(&directory);
        let destination_name = revision_file_name(source.kind, &source.output_path, 1);
        let staging = directory.join(format!(".{destination_name}.staging-1-2-0"));
        fs::write(&staging, b"private partial correction").unwrap();

        let published = publish_transcript_correction_revision_with_reader(
            &source,
            "agent-after-staging",
            &"c".repeat(64),
            "Dose is 25 mg.\n",
            |_| Ok(source.clone()),
        )
        .unwrap();

        assert!(!staging.exists());
        let second_staging = directory.join(format!(
            ".{}.staging-3-4-0",
            revision_file_name(source.kind, &source.output_path, 2)
        ));
        fs::write(&second_staging, b"another private partial correction").unwrap();
        let artifacts = live_transcript_correction_artifacts_for_deletion(
            &source.output_path,
            source.source_revision_sha256.clone(),
            source.text.clone(),
        )
        .unwrap();
        assert!(!second_staging.exists());
        assert_eq!(artifacts.len(), 1);
        assert_eq!(
            artifacts[0].0,
            Path::new(&published.revision_path)
                .file_name()
                .unwrap()
                .to_string_lossy()
        );
        fs::remove_dir_all(directory).ok();
    }

    #[test]
    fn malformed_staging_lookalike_is_never_removed_or_ignored() {
        let directory = test_directory("malformed-staging");
        let source = source(&directory);
        let destination_name = revision_file_name(source.kind, &source.output_path, 1);
        let lookalike = directory.join(format!(".{destination_name}.staging-owner"));
        fs::write(&lookalike, b"untrusted lookalike").unwrap();

        let error = publish_transcript_correction_revision_with_reader(
            &source,
            "agent-lookalike",
            &"c".repeat(64),
            "Dose is 25 mg.\n",
            |_| Ok(source.clone()),
        )
        .unwrap_err();

        assert!(error.contains("invalid revision name"));
        assert!(lookalike.exists());
        fs::remove_dir_all(directory).ok();
    }

    #[cfg(unix)]
    #[test]
    fn published_revision_is_owner_private() {
        use std::os::unix::fs::PermissionsExt;

        let directory = test_directory("private-mode");
        let source = source(&directory);
        let published = publish_transcript_correction_revision_with_reader(
            &source,
            "agent-private",
            &"c".repeat(64),
            "Dose is 25 mg.\n",
            |_| Ok(source.clone()),
        )
        .unwrap();
        assert_eq!(
            fs::metadata(published.revision_path)
                .unwrap()
                .permissions()
                .mode()
                & 0o077,
            0
        );
        fs::remove_dir_all(directory).ok();
    }
}
