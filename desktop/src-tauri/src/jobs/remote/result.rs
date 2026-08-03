use super::{
    artifact_io::{
        metadata_is_link_or_reparse, next_staging_nonce, open_no_follow_read, sha256_bytes,
        valid_sha256, validate_identifier, write_new_synced, StagingDirectory,
    },
    spool::prepare_spool_root,
};
use crate::server_connector::batch::{
    SpeakerResultRevision, TranscriptResultRevision, MAX_SPEAKER_RESULT_BYTES,
    MAX_TRANSCRIPT_RESULT_BYTES,
};
use std::{
    fs,
    path::{Path, PathBuf},
};
use time::{format_description::well_known::Rfc3339, OffsetDateTime};

const MAX_RECORDING_DURATION_MS: u64 = 4 * 60 * 60 * 1_000;

pub(in crate::jobs) fn publish_remote_result(
    job_id: &str,
    spool_root: &Path,
    result: &TranscriptResultRevision,
    speaker_result: Option<&SpeakerResultRevision>,
) -> Result<PathBuf, String> {
    validate_identifier(job_id, 128, "job ID")?;
    validate_published_result_contract(result, 1)?;
    prepare_spool_root(spool_root)?;
    let job_root = spool_root.join(job_id);
    let job_metadata = fs::symlink_metadata(&job_root)
        .map_err(|error| format!("failed to inspect prepared job directory: {error}"))?;
    if !job_metadata.is_dir() || metadata_is_link_or_reparse(&job_metadata) {
        return Err("prepared job directory is not a safe owned directory".into());
    }
    let encoded_result = serde_json::to_vec(result)
        .map_err(|error| format!("failed to encode server result revision: {error}"))?;
    if encoded_result.len() > MAX_TRANSCRIPT_RESULT_BYTES {
        return Err("server result revision is too large to publish".into());
    }
    if result.requires_speaker_result() != speaker_result.is_some() {
        return Err("server result aggregate is incomplete".into());
    }
    let encoded_speaker_result = speaker_result
        .map(serde_json::to_vec)
        .transpose()
        .map_err(|error| format!("failed to encode server speaker result: {error}"))?;
    if encoded_speaker_result
        .as_ref()
        .is_some_and(|encoded| encoded.len() > MAX_SPEAKER_RESULT_BYTES)
    {
        return Err("server speaker result revision is too large to publish".into());
    }
    if let (Some(expected), Some(encoded)) = (
        result.speaker_result_sha256.as_deref(),
        encoded_speaker_result.as_deref(),
    ) {
        if sha256_bytes(encoded) != expected {
            return Err("server result speaker companion identity differs".into());
        }
    }
    let mut transcript = result.transcript.as_bytes().to_vec();
    if !transcript.ends_with(b"\n") {
        transcript.push(b'\n');
    }
    if transcript.len() > MAX_TRANSCRIPT_RESULT_BYTES {
        return Err("server transcript is too large to publish".into());
    }

    let directory_name = format!("result-{:020}", result.revision);
    let destination = job_root.join(&directory_name);
    if destination.exists() {
        verify_published_result_directory(
            &destination,
            &encoded_result,
            &transcript,
            encoded_speaker_result.is_some(),
        )?;
        verify_published_speaker_bytes(&destination, encoded_speaker_result.as_deref())?;
        return Ok(destination.join("transcript.txt"));
    }

    let nonce = next_staging_nonce();
    let staging_path = job_root.join(format!(
        ".{directory_name}-staging-{}-{nonce}",
        std::process::id()
    ));
    let mut staging = StagingDirectory::create(staging_path)?;
    write_new_synced(&staging.path.join("result.json"), &encoded_result)?;
    write_new_synced(&staging.path.join("transcript.txt"), &transcript)?;
    if let Some(encoded) = encoded_speaker_result.as_ref() {
        write_new_synced(&staging.path.join("speaker-result.json"), encoded)?;
    }
    match staging.publish(&destination) {
        Ok(()) => {}
        Err(_error) if destination.exists() => {
            verify_published_result_directory(
                &destination,
                &encoded_result,
                &transcript,
                encoded_speaker_result.is_some(),
            )?;
            verify_published_speaker_bytes(&destination, encoded_speaker_result.as_deref())?;
            return Ok(destination.join("transcript.txt"));
        }
        Err(error) => return Err(error),
    }
    Ok(destination.join("transcript.txt"))
}

pub(in crate::jobs) struct PublishedRemoteResultBundle {
    pub(in crate::jobs) result: TranscriptResultRevision,
    pub(in crate::jobs) result_directory: PathBuf,
    pub(in crate::jobs) result_sha256: String,
    pub(in crate::jobs) text: String,
    speaker_result_path: Option<PathBuf>,
}

impl PublishedRemoteResultBundle {
    pub(in crate::jobs) fn load_speaker_result(
        &self,
    ) -> Result<Option<SpeakerResultRevision>, String> {
        let Some(path) = self.speaker_result_path.as_ref() else {
            return Ok(None);
        };
        let bytes = read_bounded_regular_artifact(
            path,
            MAX_SPEAKER_RESULT_BYTES,
            "remote speaker result revision",
        )?;
        let expected_sha256 = self
            .result
            .speaker_result_sha256
            .as_deref()
            .ok_or_else(|| "remote result omitted its speaker companion identity".to_string())?;
        if sha256_bytes(&bytes) != expected_sha256 {
            return Err("remote speaker result companion identity differs".into());
        }
        let speaker_result: SpeakerResultRevision = serde_json::from_slice(&bytes)
            .map_err(|_| "remote speaker result revision is incompatible".to_string())?;
        if speaker_result.content_sha256().as_deref() != Some(expected_sha256) {
            return Err("remote speaker result revision is not canonical".into());
        }
        Ok(Some(speaker_result))
    }
}

pub(in crate::jobs) fn read_published_remote_result_bundle(
    transcript_path: &Path,
    spool_root: &Path,
) -> Result<PublishedRemoteResultBundle, String> {
    let relative = transcript_path
        .strip_prefix(spool_root)
        .map_err(|_| "remote transcript is outside Yap's private job directory".to_string())?;
    let components = relative.components().collect::<Vec<_>>();
    if components.len() != 3 {
        return Err("remote transcript path has an invalid owned shape".into());
    }
    let job_id = normal_path_component(&components[0])
        .ok_or_else(|| "remote transcript job directory is invalid".to_string())?;
    let result_directory = normal_path_component(&components[1])
        .ok_or_else(|| "remote transcript result directory is invalid".to_string())?;
    let artifact_name = normal_path_component(&components[2])
        .ok_or_else(|| "remote transcript artifact name is invalid".to_string())?;
    validate_identifier(job_id, 128, "job ID")?;
    if artifact_name != "transcript.txt"
        || transcript_path
            != spool_root
                .join(job_id)
                .join(result_directory)
                .join("transcript.txt")
    {
        return Err("remote transcript path is not canonical".into());
    }
    let revision_text = result_directory
        .strip_prefix("result-")
        .filter(|value| value.len() == 20 && value.bytes().all(|byte| byte.is_ascii_digit()))
        .ok_or_else(|| "remote transcript result revision is invalid".to_string())?;
    let revision = revision_text
        .parse::<u64>()
        .map_err(|_| "remote transcript result revision is invalid".to_string())?;
    if revision == 0 {
        return Err("remote transcript result revision is invalid".into());
    }

    for directory in [spool_root.to_path_buf(), spool_root.join(job_id)] {
        let metadata = fs::symlink_metadata(&directory)
            .map_err(|error| format!("failed to inspect remote result owner: {error}"))?;
        if !metadata.is_dir() || metadata_is_link_or_reparse(&metadata) {
            return Err("remote result owner is not a safe Yap directory".into());
        }
    }
    let destination = spool_root.join(job_id).join(result_directory);
    let destination_metadata = fs::symlink_metadata(&destination)
        .map_err(|error| format!("failed to inspect remote result revision: {error}"))?;
    if !destination_metadata.is_dir() || metadata_is_link_or_reparse(&destination_metadata) {
        return Err("remote result revision is not a safe Yap directory".into());
    }
    let result_path = destination.join("result.json");
    let result_bytes = read_bounded_regular_artifact(
        &result_path,
        MAX_TRANSCRIPT_RESULT_BYTES,
        "remote result revision",
    )?;
    let result: TranscriptResultRevision = serde_json::from_slice(&result_bytes)
        .map_err(|_| "remote result revision is incompatible".to_string())?;
    validate_published_result_contract(&result, revision)?;
    let speaker_path = destination.join("speaker-result.json");
    let speaker_result_path = speaker_path.exists().then_some(speaker_path);
    if result.requires_speaker_result() != speaker_result_path.is_some() {
        return Err("published remote result aggregate is incomplete".into());
    }
    let mut expected_transcript = result.transcript.as_bytes().to_vec();
    if !expected_transcript.ends_with(b"\n") {
        expected_transcript.push(b'\n');
    }
    verify_published_result_directory(
        &destination,
        &result_bytes,
        &expected_transcript,
        speaker_result_path.is_some(),
    )?;
    if let Some(path) = speaker_result_path.as_ref() {
        bounded_regular_artifact_metadata(
            path,
            MAX_SPEAKER_RESULT_BYTES,
            "remote speaker result revision",
        )?;
    }
    let text = String::from_utf8(expected_transcript)
        .map_err(|_| "remote transcript is not valid UTF-8".to_string())?;
    Ok(PublishedRemoteResultBundle {
        result,
        result_directory: destination,
        result_sha256: sha256_bytes(&result_bytes),
        speaker_result_path,
        text,
    })
}

pub(in crate::jobs) fn discover_published_remote_result_bundle(
    job_id: &str,
    spool_root: &Path,
) -> Result<Option<PublishedRemoteResultBundle>, String> {
    validate_identifier(job_id, 128, "job ID")?;
    let job_root = spool_root.join(job_id);
    let job_metadata = match fs::symlink_metadata(&job_root) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(format!("failed to inspect prepared job directory: {error}")),
    };
    if !job_metadata.is_dir() || metadata_is_link_or_reparse(&job_metadata) {
        return Err("prepared job directory is not a safe owned directory".into());
    }
    let mut transcript_paths = Vec::new();
    for entry in fs::read_dir(&job_root)
        .map_err(|error| format!("failed to inspect prepared job contents: {error}"))?
    {
        let entry =
            entry.map_err(|error| format!("failed to inspect prepared job entry: {error}"))?;
        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            continue;
        };
        if !name.starts_with("result-") {
            continue;
        }
        let revision = name.strip_prefix("result-").unwrap_or_default();
        if revision.len() != 20 || !revision.bytes().all(|byte| byte.is_ascii_digit()) {
            return Err("published remote result directory has an invalid revision".into());
        }
        transcript_paths.push(entry.path().join("transcript.txt"));
    }
    match transcript_paths.as_slice() {
        [] => Ok(None),
        [transcript_path] => {
            read_published_remote_result_bundle(transcript_path, spool_root).map(Some)
        }
        _ => Err("saving job has more than one published result revision".into()),
    }
}

fn normal_path_component<'a>(component: &'a std::path::Component<'a>) -> Option<&'a str> {
    match component {
        std::path::Component::Normal(value) => value.to_str(),
        _ => None,
    }
}

pub(super) fn read_bounded_regular_artifact(
    path: &Path,
    maximum_bytes: usize,
    label: &str,
) -> Result<Vec<u8>, String> {
    let metadata = bounded_regular_artifact_metadata(path, maximum_bytes, label)?;
    let mut file =
        open_no_follow_read(path).map_err(|error| format!("failed to open {label}: {error}"))?;
    let opened = file
        .metadata()
        .map_err(|error| format!("failed to inspect opened {label}: {error}"))?;
    if !opened.is_file() || metadata_is_link_or_reparse(&opened) || opened.len() != metadata.len() {
        return Err(format!("opened {label} differs from its owned path"));
    }
    let bytes = crate::bounded_file::read_to_end(&mut file, maximum_bytes)
        .map_err(|error| format!("failed to read {label}: {error}"))?;
    if bytes.len() != metadata.len() as usize {
        return Err(format!("{label} changed while it was read"));
    }
    Ok(bytes)
}

fn bounded_regular_artifact_metadata(
    path: &Path,
    maximum_bytes: usize,
    label: &str,
) -> Result<fs::Metadata, String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("failed to inspect {label}: {error}"))?;
    if !metadata.is_file()
        || metadata_is_link_or_reparse(&metadata)
        || metadata.len() == 0
        || metadata.len() > maximum_bytes as u64
    {
        return Err(format!("{label} is not a bounded regular Yap artifact"));
    }
    Ok(metadata)
}

pub(super) fn validate_published_result_contract(
    result: &TranscriptResultRevision,
    expected_revision: u64,
) -> Result<(), String> {
    validate_identifier(&result.session_id, 128, "result session ID")?;
    let timestamp_valid = result.created_at_utc.ends_with('Z')
        && result.created_at_utc.len() <= 64
        && OffsetDateTime::parse(&result.created_at_utc, &Rfc3339).is_ok();
    let language_valid = result.language.as_ref().is_some_and(|language| {
        !language.language_bcp47.is_empty()
            && language.language_bcp47.len() <= 35
            && language
                .language_bcp47
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
            && language
                .confidence
                .is_none_or(|confidence| (0.0..=1.0).contains(&confidence))
    });
    let provenance_valid = !result.model_provenance.is_empty()
        && result.model_provenance.len() <= 8
        && result.model_provenance.iter().all(|model| {
            [
                model.model_id.as_str(),
                model.revision.as_str(),
                model.calibration_revision.as_str(),
            ]
            .iter()
            .all(|value| !value.is_empty() && value.len() <= 256)
        });
    if result.revision != expected_revision
        || result.authority != "server_authoritative"
        || !timestamp_valid
        || !valid_sha256(&result.capture_manifest_sha256)
        || result
            .previous_result_sha256
            .as_deref()
            .is_some_and(|value| !valid_sha256(value))
        || result
            .speaker_result_sha256
            .as_deref()
            .is_some_and(|value| !valid_sha256(value))
        || !matches!(result.status.as_str(), "complete" | "partial")
        || (result.status == "partial" && !result.requires_speaker_result())
        || !language_valid
        || !result.transcript_is_canonical()
        || !result.language_evidence_is_valid(None, MAX_RECORDING_DURATION_MS)
        || !result.alignment_is_valid(MAX_RECORDING_DURATION_MS)
        || !provenance_valid
    {
        return Err("remote result revision conflicts with the published transcript".into());
    }
    Ok(())
}

fn verify_published_result_directory(
    destination: &Path,
    expected_result: &[u8],
    expected_transcript: &[u8],
    has_speaker_result: bool,
) -> Result<(), String> {
    let metadata = fs::symlink_metadata(destination)
        .map_err(|error| format!("failed to inspect published result directory: {error}"))?;
    if !metadata.is_dir() || metadata_is_link_or_reparse(&metadata) {
        return Err("published result path is not a safe owned directory".into());
    }
    let mut names = fs::read_dir(destination)
        .map_err(|error| format!("failed to inspect published result contents: {error}"))?
        .map(|entry| {
            entry
                .map(|entry| entry.file_name())
                .map_err(|error| format!("failed to inspect published result entry: {error}"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    names.sort();
    let expected_names = if has_speaker_result {
        vec!["result.json", "speaker-result.json", "transcript.txt"]
    } else {
        vec!["result.json", "transcript.txt"]
    };
    if names != expected_names {
        return Err("published result directory has unexpected contents".into());
    }
    for (name, expected) in [
        ("result.json", expected_result),
        ("transcript.txt", expected_transcript),
    ] {
        let path = destination.join(name);
        let metadata = fs::symlink_metadata(&path)
            .map_err(|error| format!("failed to inspect published result artifact: {error}"))?;
        if !metadata.is_file()
            || metadata_is_link_or_reparse(&metadata)
            || metadata.len() != expected.len() as u64
        {
            return Err("published result artifact conflicts with its declaration".into());
        }
        let mut file = open_no_follow_read(&path)
            .map_err(|error| format!("failed to open published result artifact: {error}"))?;
        let actual = crate::bounded_file::read_to_end(&mut file, expected.len())
            .map_err(|error| format!("failed to read published result artifact: {error}"))?;
        if actual != expected {
            return Err("published result artifact conflicts with its immutable content".into());
        }
    }
    Ok(())
}

fn verify_published_speaker_bytes(
    destination: &Path,
    expected_speaker_result: Option<&[u8]>,
) -> Result<(), String> {
    if let Some(expected) = expected_speaker_result {
        let actual = read_bounded_regular_artifact(
            &destination.join("speaker-result.json"),
            MAX_SPEAKER_RESULT_BYTES,
            "published speaker result artifact",
        )?;
        if actual != expected {
            return Err("published speaker result conflicts with its immutable content".into());
        }
    }
    Ok(())
}
