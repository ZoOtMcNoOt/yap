use super::{
    artifact_io::{
        metadata_is_link_or_reparse, next_staging_nonce, open_no_follow_read, sha256_bytes,
        sha256_reader, valid_sha256, validate_identifier, write_new_synced, StagingDirectory,
    },
    preprocessing::{
        AdvisoryVadSession, ImportedDecodedSourceEvidence, ImportedNormalizationEvidence,
        ImportedPreprocessingEvidence, CAPTURE_MANIFEST_SCHEMA_VERSION, MAX_CAPTURE_MANIFEST_BYTES,
    },
    spool::prepare_spool_root,
    wav::inspect_pcm_wav,
};
use crate::{
    audio::session::{
        OwnerNamespace, SessionId, SessionMetadata, SessionMode, SessionOrigin, TriggerMode,
    },
    jobs::{NewClientPreflightArtifact, NewJobChunk, NewPreparedRemoteJob},
    language::{RecordingLanguageDecision, RecordingLanguageMode},
    server_connector::batch::{
        CaptureChunkReference, CaptureManifestReference, ContentIdentity,
        CreateRecordingJobRequest, ServerReplayKey, UploadTrack,
    },
    server_connector::{
        lid::{
            select_lid_probe_windows, LidManualReason, LidPreflightRequest,
            LidPreflightSourceIdentity, LidProbeWindow,
        },
        AsrCapabilityCatalog,
    },
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Seek, SeekFrom, Write},
    path::{Path, PathBuf},
    time::{Duration, SystemTime},
};

#[cfg(test)]
use super::preprocessing::AdvisoryVadEngine;

pub(super) const CHUNK_PCM_BYTES: usize = 960_000;
const PCM_BYTES_PER_MILLISECOND: usize = 32;
const VAD_FEED_PCM_BYTES: usize = 512 * 2;
const RETENTION_SECONDS: u64 = 30 * 24 * 60 * 60;
const CLIENT_PREFLIGHT_SCHEMA_VERSION: u16 = 1;
const CLIENT_PREFLIGHT_MANIFEST_NAME: &str = "client-preflight.json";
const MAX_CLIENT_PREFLIGHT_MANIFEST_BYTES: usize = 1024 * 1024;
#[cfg(test)]
const TEST_ASR_CATALOG_REVISION: &str =
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

pub(in crate::jobs) struct PreparedRemoteChunk {
    pub(in crate::jobs) reference: CaptureChunkReference,
    pub(in crate::jobs) artifact_path: PathBuf,
}

pub(in crate::jobs) struct PreparedRemoteJob {
    pub(in crate::jobs) request: CreateRecordingJobRequest,
    pub(in crate::jobs) chunks: Vec<PreparedRemoteChunk>,
    pub(in crate::jobs) capture_manifest_path: PathBuf,
    pub(in crate::jobs) owner_namespace: String,
}

pub(in crate::jobs) struct PreparedClientPreflight {
    manifest_path: PathBuf,
    manifest_sha256: String,
    manifest: ImportedClientPreflightManifest,
}

pub(in crate::jobs) struct ImportedPcmWavPreparation<'a> {
    pub(in crate::jobs) job_id: &'a str,
    pub(in crate::jobs) display_name: &'a str,
    pub(in crate::jobs) source: &'a mut File,
    pub(in crate::jobs) spool_root: &'a Path,
    pub(in crate::jobs) owner_namespace: &'a OwnerNamespace,
    pub(in crate::jobs) started_at: SystemTime,
    pub(in crate::jobs) language_decision: &'a RecordingLanguageDecision,
    pub(in crate::jobs) asr_catalog_revision: &'a str,
    /// Set when `source` is a canonical file this build decoded from a
    /// compressed import. Both preparation entry points carry it, so neither
    /// can report a decoded source as an identity copy.
    pub(in crate::jobs) decoded_from: Option<super::decode::DecodedSource>,
}

pub(in crate::jobs) struct ImportedClientPreflightPreparation<'a> {
    pub(in crate::jobs) job_id: &'a str,
    pub(in crate::jobs) display_name: &'a str,
    pub(in crate::jobs) source: &'a mut File,
    pub(in crate::jobs) spool_root: &'a Path,
    pub(in crate::jobs) owner_namespace: &'a OwnerNamespace,
    pub(in crate::jobs) started_at: SystemTime,
    /// Set when `source` is a canonical file this build decoded from a
    /// compressed import, so the normalization record can say so.
    pub(in crate::jobs) decoded_from: Option<super::decode::DecodedSource>,
}

pub(in crate::jobs) enum ImportedLidPreparation {
    Manual {
        source_samples: u64,
        source_pcm_sha256: String,
        reason: LidManualReason,
    },
    Dispatch {
        request: Box<LidPreflightRequest>,
    },
}

impl PreparedClientPreflight {
    pub(in crate::jobs) fn into_ledger_state(
        self,
    ) -> (NewClientPreflightArtifact, ImportedPreprocessingEvidence) {
        let artifact = NewClientPreflightArtifact {
            manifest_path: self.manifest_path,
            manifest_sha256: self.manifest_sha256,
            source_pcm_sha256: self
                .manifest
                .preprocessing
                .normalization()
                .source_pcm_sha256()
                .into(),
            source_sample_count: self
                .manifest
                .preprocessing
                .normalization()
                .source_sample_count(),
        };
        (artifact, self.manifest.preprocessing)
    }

    pub(in crate::jobs) fn prepare_lid_request(
        &self,
        spool_root: &Path,
        catalog: &AsrCapabilityCatalog,
        request_id: String,
    ) -> Result<ImportedLidPreparation, String> {
        let capability = catalog
            .lid_preflight()
            .ok_or_else(|| "server did not advertise language preflight".to_string())?;
        let source_samples = self
            .manifest
            .preprocessing
            .normalization()
            .source_sample_count();
        let source_pcm_sha256 = self
            .manifest
            .preprocessing
            .normalization()
            .source_pcm_sha256()
            .to_owned();
        let selection = select_lid_probe_windows(
            capability,
            source_samples,
            self.manifest.preprocessing.vad().intervals(),
        )
        .map_err(|error| error.to_string())?;
        let Some(windows) = selection.windows() else {
            return Ok(ImportedLidPreparation::Manual {
                source_samples,
                source_pcm_sha256,
                reason: selection
                    .manual_reason()
                    .expect("manual LID selection has a reason"),
            });
        };
        let probes = [
            read_probe_pcm(&self.manifest, spool_root, &windows[0])?,
            read_probe_pcm(&self.manifest, spool_root, &windows[1])?,
            read_probe_pcm(&self.manifest, spool_root, &windows[2])?,
            read_probe_pcm(&self.manifest, spool_root, &windows[3])?,
            read_probe_pcm(&self.manifest, spool_root, &windows[4])?,
        ];
        let source =
            LidPreflightSourceIdentity::try_new(request_id, source_samples, source_pcm_sha256)
                .map_err(|error| error.to_string())?;
        let request =
            LidPreflightRequest::from_selected_probes(catalog, source, &selection, probes)
                .map_err(|error| error.to_string())?;
        Ok(ImportedLidPreparation::Dispatch {
            request: Box::new(request),
        })
    }
}

impl PreparedRemoteJob {
    pub(in crate::jobs) fn into_ledger_state(self) -> Result<NewPreparedRemoteJob, String> {
        let create_request_json = serde_json::to_string(&self.request)
            .map_err(|error| format!("failed to encode prepared server request: {error}"))?;
        let capture_manifest_sha256 = self.request.capture_manifest.sha256.clone();
        let chunks = self
            .chunks
            .into_iter()
            .map(|chunk| NewJobChunk {
                owner_namespace: self.owner_namespace.clone(),
                session_id: chunk.reference.replay_key.session_id,
                track_id: chunk.reference.replay_key.track_id,
                sequence_start: chunk.reference.replay_key.sequence_start,
                sequence_end: chunk.reference.replay_key.sequence_end,
                content_sha256: chunk.reference.content_identity.sha256,
                content_byte_length: chunk.reference.content_identity.byte_length,
                artifact_path: chunk.artifact_path,
                upload_offset: 0,
                acknowledged_object_id: None,
                acknowledged_at_ms: None,
            })
            .collect();
        Ok(NewPreparedRemoteJob {
            create_request_json,
            capture_manifest_path: self.capture_manifest_path,
            capture_manifest_sha256,
            chunks,
        })
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ImportedCaptureManifest<'a> {
    schema_version: u16,
    session_id: &'a str,
    source: ImportedSourceIdentity<'a>,
    preprocessing: ImportedPreprocessingEvidence,
    language_decision: &'a RecordingLanguageDecision,
    chunks: &'a [CaptureChunkReference],
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ImportedSourceIdentity<'a> {
    display_name: &'a str,
    sha256: String,
    byte_length: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ImportedClientPreflightManifest {
    schema_version: u16,
    job_id: String,
    display_name: String,
    owner_namespace: String,
    metadata: SessionMetadata,
    source: ImportedOwnedSourceIdentity,
    preprocessing: ImportedPreprocessingEvidence,
    tracks: Vec<UploadTrack>,
    chunks: Vec<ImportedClientPreflightChunk>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ImportedOwnedSourceIdentity {
    display_name: String,
    sha256: String,
    byte_length: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ImportedClientPreflightChunk {
    reference: CaptureChunkReference,
    filename: String,
}

#[cfg(test)]
pub(in crate::jobs) fn prepare_imported_pcm_wav(
    job_id: &str,
    display_name: &str,
    source: &mut File,
    spool_root: &Path,
    owner_namespace: &OwnerNamespace,
    started_at: SystemTime,
    language_decision: &RecordingLanguageDecision,
) -> Result<PreparedRemoteJob, String> {
    prepare_imported_pcm_wav_with_cancellation(
        ImportedPcmWavPreparation {
            job_id,
            display_name,
            source,
            spool_root,
            owner_namespace,
            started_at,
            language_decision,
            asr_catalog_revision: TEST_ASR_CATALOG_REVISION,
            // This test-only entry point takes an already-canonical source.
            decoded_from: None,
        },
        || Ok(()),
    )
}

pub(in crate::jobs) fn prepare_imported_pcm_wav_with_cancellation(
    preparation: ImportedPcmWavPreparation<'_>,
    ensure_active: impl FnMut() -> Result<(), String>,
) -> Result<PreparedRemoteJob, String> {
    let ImportedPcmWavPreparation {
        job_id,
        display_name,
        source,
        spool_root,
        owner_namespace,
        started_at,
        language_decision,
        asr_catalog_revision,
        decoded_from,
    } = preparation;
    let preflight = prepare_imported_client_preflight_with_cancellation(
        ImportedClientPreflightPreparation {
            job_id,
            display_name,
            source,
            spool_root,
            owner_namespace,
            started_at,
            decoded_from,
        },
        ensure_active,
    )?;
    finalize_imported_client_preflight(
        &preflight,
        spool_root,
        language_decision,
        asr_catalog_revision,
    )
}

pub(in crate::jobs) fn prepare_imported_client_preflight_with_cancellation(
    preparation: ImportedClientPreflightPreparation<'_>,
    ensure_active: impl FnMut() -> Result<(), String>,
) -> Result<PreparedClientPreflight, String> {
    let mut detector = crate::stt::silero_vad::SileroVadDetector::load();
    let vad = match detector.as_mut() {
        Ok(detector) => AdvisoryVadSession::running(detector),
        Err(crate::stt::error::SttError::ModelMissing) => {
            AdvisoryVadSession::unavailable("artifact_unavailable")
        }
        Err(crate::stt::error::SttError::ModelCorrupt) => {
            AdvisoryVadSession::unavailable("artifact_corrupt")
        }
        Err(_) => AdvisoryVadSession::unavailable("runtime_unavailable"),
    };
    prepare_imported_client_preflight_impl(preparation, vad, ensure_active)
}

#[cfg(test)]
pub(super) fn prepare_imported_pcm_wav_with_advisory_vad_for_test(
    preparation: ImportedPcmWavPreparation<'_>,
    vad: &mut dyn AdvisoryVadEngine,
) -> Result<PreparedRemoteJob, String> {
    let ImportedPcmWavPreparation {
        job_id,
        display_name,
        source,
        spool_root,
        owner_namespace,
        started_at,
        language_decision,
        asr_catalog_revision,
        decoded_from,
    } = preparation;
    let preflight = prepare_imported_client_preflight_impl(
        ImportedClientPreflightPreparation {
            job_id,
            display_name,
            source,
            spool_root,
            owner_namespace,
            started_at,
            decoded_from,
        },
        AdvisoryVadSession::running(vad),
        || Ok(()),
    )?;
    finalize_imported_client_preflight(
        &preflight,
        spool_root,
        language_decision,
        asr_catalog_revision,
    )
}

fn prepare_imported_client_preflight_impl(
    preparation: ImportedClientPreflightPreparation<'_>,
    mut vad: AdvisoryVadSession<'_>,
    mut ensure_active: impl FnMut() -> Result<(), String>,
) -> Result<PreparedClientPreflight, String> {
    let ImportedClientPreflightPreparation {
        job_id,
        display_name,
        source,
        spool_root,
        owner_namespace,
        started_at,
        decoded_from,
    } = preparation;
    ensure_active()?;
    validate_identifier(job_id, 128, "job ID")?;
    if display_name.is_empty() || display_name.len() > 256 {
        return Err("display name is outside the server contract".into());
    }
    // This external-file inspection is only an early bounded-format preflight. All
    // authoritative hashes, VAD evidence, and chunks below consume one owned
    // snapshot so an in-place source mutation cannot bind evidence to other bytes.
    let preflight = inspect_pcm_wav(source, &mut ensure_active)?;
    prepare_spool_root(spool_root)?;
    let destination = spool_root.join(job_id);
    if destination.exists() {
        return Err("a prepared spool already exists for this recording job".into());
    }
    let nonce = next_staging_nonce();
    let staging_path = spool_root.join(format!(".{job_id}-{}-{nonce}.part", std::process::id()));
    let mut staging = StagingDirectory::create(staging_path)?;
    let snapshot_path = staging.path.join("admitted-source.wav");
    let mut admitted_source = freeze_selected_source(
        source,
        &snapshot_path,
        preflight.source_bytes,
        &mut ensure_active,
    )?;
    let wav = inspect_pcm_wav(&mut admitted_source, &mut ensure_active)?;
    ensure_active()?;
    let source_sha256 = sha256_reader(&mut admitted_source, wav.source_bytes, &mut ensure_active)?;
    admitted_source
        .seek(SeekFrom::Start(wav.data_offset))
        .map_err(|error| format!("failed to seek admitted WAV data: {error}"))?;

    let session_id = format!("s-{}", job_id.strip_prefix("job-").unwrap_or(job_id));
    let session = SessionId::new(session_id.clone())?;
    let mut metadata = SessionMetadata::new(
        session,
        SessionMode::Meeting,
        SessionOrigin::ImportedFile,
        TriggerMode::Toggle,
        started_at,
        None,
        None,
        None,
        Vec::new(),
        Some(started_at + Duration::from_secs(RETENTION_SECONDS)),
    )?;
    metadata.privacy_policy_version = "development-only".into();

    let track_id = "track-1".to_string();
    let mut remaining = wav.data_bytes;
    let mut sequence_start = 0_u64;
    let mut start_ms = 0_u64;
    let mut references = Vec::new();
    let mut staged_names = Vec::new();
    let source_sample_count = wav.data_bytes / 2;
    let mut source_pcm_digest = Sha256::new();
    let mut output_pcm_digest = Sha256::new();
    let mut padding_samples = 0_u16;
    while remaining > 0 {
        ensure_active()?;
        let read_length = remaining.min(CHUNK_PCM_BYTES as u64) as usize;
        let mut body = vec![0_u8; read_length];
        admitted_source
            .read_exact(&mut body)
            .map_err(|error| format!("failed to read admitted WAV audio: {error}"))?;
        remaining -= read_length as u64;
        source_pcm_digest.update(&body);
        if vad.is_running() {
            for window in body.chunks(VAD_FEED_PCM_BYTES) {
                ensure_active()?;
                vad.accept_pcm16(window, &mut ensure_active)?;
                ensure_active()?;
                if !vad.is_running() {
                    break;
                }
            }
        }
        if remaining == 0 {
            let padded_length =
                body.len().div_ceil(PCM_BYTES_PER_MILLISECOND) * PCM_BYTES_PER_MILLISECOND;
            if padded_length != body.len() {
                padding_samples = u16::try_from((padded_length - body.len()) / 2)
                    .map_err(|_| "imported WAV padding is out of range")?;
                body.resize(padded_length, 0);
            }
        }
        output_pcm_digest.update(&body);
        let sample_count = u64::try_from(body.len() / 2)
            .map_err(|_| "imported WAV sample count is out of range")?;
        let sequence_end = sequence_start
            .checked_add(sample_count)
            .and_then(|value| value.checked_sub(1))
            .ok_or_else(|| "imported WAV sequence range overflowed".to_string())?;
        let duration_ms = u32::try_from(body.len() / PCM_BYTES_PER_MILLISECOND)
            .map_err(|_| "imported WAV chunk duration is out of range")?;
        let filename = format!("{track_id}-{sequence_start}-{sequence_end}.pcm");
        write_new_synced(&staging.path.join(&filename), &body)?;
        let reference = CaptureChunkReference {
            replay_key: ServerReplayKey {
                schema_version: 1,
                session_id: session_id.clone(),
                track_id: track_id.clone(),
                sequence_start,
                sequence_end,
            },
            content_identity: ContentIdentity {
                sha256: sha256_bytes(&body),
                byte_length: body.len() as u64,
            },
            audio_codec: "pcm_s16le".into(),
            sample_rate_hz: 16_000,
            channels: 1,
            start_ms,
            duration_ms,
        };
        start_ms = start_ms
            .checked_add(u64::from(duration_ms))
            .ok_or_else(|| "imported WAV timeline overflowed".to_string())?;
        sequence_start = sequence_end
            .checked_add(1)
            .ok_or_else(|| "imported WAV sequence overflowed".to_string())?;
        references.push(reference);
        staged_names.push(filename);
    }
    if references.is_empty() {
        return Err("imported WAV contains no audio samples".into());
    }
    drop(admitted_source);
    fs::remove_file(&snapshot_path)
        .map_err(|error| format!("failed to remove transient admitted WAV snapshot: {error}"))?;
    let output_sample_count = sequence_start;
    if output_sample_count
        != source_sample_count
            .checked_add(u64::from(padding_samples))
            .ok_or_else(|| "imported WAV normalization length overflowed".to_string())?
    {
        return Err("imported WAV normalization changed source-time length".into());
    }

    let source_pcm_sha256 = format_sha256(source_pcm_digest.finalize().as_slice());
    let output_pcm_sha256 = format_sha256(output_pcm_digest.finalize().as_slice());
    let normalization = match decoded_from {
        Some(decoded) => ImportedNormalizationEvidence::decoded_to_canonical_pcm16(
            source_sha256.clone(),
            source_pcm_sha256,
            output_pcm_sha256,
            source_sample_count,
            output_sample_count,
            padding_samples,
            ImportedDecodedSourceEvidence::new(
                decoded.source_codec,
                decoded.source_sample_rate_hz,
                decoded.source_channels,
                decoded.source_frame_count,
            )
            .map_err(|reason| format!("decoded source evidence is invalid: {reason}"))?,
        ),
        None => ImportedNormalizationEvidence::canonical_pcm16_identity(
            source_sha256.clone(),
            source_pcm_sha256,
            output_pcm_sha256,
            source_sample_count,
            output_sample_count,
            padding_samples,
        ),
    };
    ensure_active()?;
    let vad_evidence = vad.finish(source_sample_count, &mut ensure_active)?;
    ensure_active()?;
    let preprocessing = ImportedPreprocessingEvidence::new(normalization, vad_evidence);
    let tracks = vec![UploadTrack {
        track_id,
        source: serde_json::json!({
            "kind": "imported",
            "provenance": "unknown"
        }),
        device_id: None,
        original_sample_rate_hz: 16_000,
        original_channels: 1,
    }];
    let chunks = references
        .into_iter()
        .zip(staged_names)
        .map(|(reference, filename)| ImportedClientPreflightChunk {
            reference,
            filename,
        })
        .collect();
    let manifest = ImportedClientPreflightManifest {
        schema_version: CLIENT_PREFLIGHT_SCHEMA_VERSION,
        job_id: job_id.into(),
        display_name: display_name.into(),
        owner_namespace: owner_namespace.as_str().into(),
        metadata,
        source: ImportedOwnedSourceIdentity {
            display_name: display_name.into(),
            sha256: source_sha256,
            byte_length: wav.source_bytes,
        },
        preprocessing,
        tracks,
        chunks,
    };
    validate_client_preflight_manifest(&manifest, job_id)?;
    let manifest_bytes = serde_json::to_vec(&manifest)
        .map_err(|error| format!("failed to encode client preflight manifest: {error}"))?;
    if manifest_bytes.len() > MAX_CLIENT_PREFLIGHT_MANIFEST_BYTES {
        return Err("client preflight manifest exceeds its evidence limit".into());
    }
    ensure_active()?;
    write_new_synced(
        &staging.path.join(CLIENT_PREFLIGHT_MANIFEST_NAME),
        &manifest_bytes,
    )?;
    ensure_active()?;
    staging.publish(&destination)?;
    Ok(PreparedClientPreflight {
        manifest_path: destination.join(CLIENT_PREFLIGHT_MANIFEST_NAME),
        manifest_sha256: sha256_bytes(&manifest_bytes),
        manifest,
    })
}

pub(in crate::jobs) fn load_imported_client_preflight(
    job_id: &str,
    manifest_path: &Path,
    manifest_sha256: &str,
    spool_root: &Path,
) -> Result<PreparedClientPreflight, String> {
    validate_identifier(job_id, 128, "job ID")?;
    if !valid_sha256(manifest_sha256) || !manifest_path.is_absolute() || !spool_root.is_absolute() {
        return Err("client preflight manifest identity is invalid".into());
    }
    prepare_spool_root(spool_root)?;
    let expected_path = spool_root.join(job_id).join(CLIENT_PREFLIGHT_MANIFEST_NAME);
    if manifest_path != expected_path {
        return Err("client preflight manifest path has an invalid owned shape".into());
    }
    let parent = manifest_path
        .parent()
        .ok_or_else(|| "client preflight manifest has no parent".to_string())?;
    let parent_metadata = fs::symlink_metadata(parent)
        .map_err(|error| format!("failed to inspect client preflight directory: {error}"))?;
    if !parent_metadata.is_dir() || metadata_is_link_or_reparse(&parent_metadata) {
        return Err("client preflight directory is not a safe owned directory".into());
    }
    let path_metadata = fs::symlink_metadata(manifest_path)
        .map_err(|error| format!("failed to inspect client preflight manifest: {error}"))?;
    if !path_metadata.is_file()
        || metadata_is_link_or_reparse(&path_metadata)
        || path_metadata.len() == 0
        || path_metadata.len() > MAX_CLIENT_PREFLIGHT_MANIFEST_BYTES as u64
    {
        return Err("client preflight manifest is not a bounded regular file".into());
    }
    let mut file = open_no_follow_read(manifest_path)
        .map_err(|error| format!("failed to open client preflight manifest: {error}"))?;
    let opened = file
        .metadata()
        .map_err(|error| format!("failed to inspect opened client preflight manifest: {error}"))?;
    if !opened.is_file()
        || metadata_is_link_or_reparse(&opened)
        || opened.len() != path_metadata.len()
    {
        return Err("opened client preflight manifest changed identity".into());
    }
    let bytes = crate::bounded_file::read_to_end(
        &mut file,
        usize::try_from(path_metadata.len())
            .map_err(|_| "client preflight manifest length is out of range")?,
    )
    .map_err(|error| format!("failed to read client preflight manifest: {error}"))?;
    if bytes.len() as u64 != path_metadata.len() || sha256_bytes(&bytes) != manifest_sha256 {
        return Err("client preflight manifest differs from its durable identity".into());
    }
    let manifest: ImportedClientPreflightManifest = serde_json::from_slice(&bytes)
        .map_err(|_| "client preflight manifest is invalid JSON".to_string())?;
    if serde_json::to_vec(&manifest).ok().as_deref() != Some(bytes.as_slice()) {
        return Err("client preflight manifest is not canonical JSON".into());
    }
    validate_client_preflight_manifest(&manifest, job_id)?;
    Ok(PreparedClientPreflight {
        manifest_path: manifest_path.to_path_buf(),
        manifest_sha256: manifest_sha256.into(),
        manifest,
    })
}

pub(in crate::jobs) fn finalize_imported_client_preflight(
    preflight: &PreparedClientPreflight,
    spool_root: &Path,
    language_decision: &RecordingLanguageDecision,
    asr_catalog_revision: &str,
) -> Result<PreparedRemoteJob, String> {
    if !valid_sha256(asr_catalog_revision) {
        return Err("ASR catalog revision is outside the server contract".into());
    }
    let language_bcp47 = match language_decision.mode {
        RecordingLanguageMode::Fixed => language_decision
            .language_bcp47
            .as_ref()
            .ok_or_else(|| "fixed language routing requires a BCP-47 language".to_string())?
            .clone(),
        RecordingLanguageMode::Dynamic => {
            if language_decision.language_bcp47.is_some() {
                return Err("dynamic language routing cannot freeze a fixed locale".into());
            }
            "und".to_string()
        }
    };
    let verified = load_imported_client_preflight(
        &preflight.manifest.job_id,
        &preflight.manifest_path,
        &preflight.manifest_sha256,
        spool_root,
    )?;
    let manifest = verified.manifest;
    let destination = spool_root.join(&manifest.job_id);
    let references = manifest
        .chunks
        .iter()
        .map(|chunk| chunk.reference.clone())
        .collect::<Vec<_>>();
    let mut preprocessing = manifest.preprocessing.clone();
    let mut capture_manifest = ImportedCaptureManifest {
        schema_version: CAPTURE_MANIFEST_SCHEMA_VERSION,
        session_id: manifest.metadata.session_id.as_str(),
        source: ImportedSourceIdentity {
            display_name: &manifest.source.display_name,
            sha256: manifest.source.sha256.clone(),
            byte_length: manifest.source.byte_length,
        },
        preprocessing: preprocessing.clone(),
        language_decision,
        chunks: &references,
    };
    let mut manifest_bytes = serde_json::to_vec(&capture_manifest)
        .map_err(|error| format!("failed to encode capture manifest: {error}"))?;
    if manifest_bytes.len() > MAX_CAPTURE_MANIFEST_BYTES {
        preprocessing.discard_vad_intervals("manifest_limit_exceeded");
        capture_manifest.preprocessing = preprocessing.clone();
        manifest_bytes = serde_json::to_vec(&capture_manifest)
            .map_err(|error| format!("failed to encode bounded capture manifest: {error}"))?;
    }
    if manifest_bytes.len() > MAX_CAPTURE_MANIFEST_BYTES {
        return Err("capture manifest exceeds the preprocessing evidence limit".into());
    }
    let capture_manifest_path = destination.join("capture-manifest.json");
    write_or_verify_synced(&capture_manifest_path, &manifest_bytes)?;
    let capture_manifest_reference = CaptureManifestReference {
        schema_version: CAPTURE_MANIFEST_SCHEMA_VERSION,
        session_id: manifest.metadata.session_id.as_str().into(),
        sha256: sha256_bytes(&manifest_bytes),
        byte_length: manifest_bytes.len() as u64,
    };
    let chunks = manifest
        .chunks
        .iter()
        .map(|chunk| PreparedRemoteChunk {
            reference: chunk.reference.clone(),
            artifact_path: destination.join(&chunk.filename),
        })
        .collect();
    let mut metadata = manifest.metadata;
    metadata.locale_hint_bcp47 = Some(language_bcp47.clone());
    metadata.preferred_languages_bcp47 = vec![language_bcp47];
    Ok(PreparedRemoteJob {
        request: CreateRecordingJobRequest {
            display_name: manifest.display_name,
            metadata,
            language_decision: language_decision.clone(),
            asr_catalog_revision: Some(asr_catalog_revision.into()),
            tracks: manifest.tracks,
            route: "server_batch".into(),
            capture_manifest: capture_manifest_reference,
            preprocessing_evidence: Some(preprocessing),
            chunks: references,
        },
        chunks,
        capture_manifest_path,
        owner_namespace: manifest.owner_namespace,
    })
}

fn validate_client_preflight_manifest(
    manifest: &ImportedClientPreflightManifest,
    job_id: &str,
) -> Result<(), String> {
    let expected_session_id = format!("s-{}", job_id.strip_prefix("job-").unwrap_or(job_id));
    if manifest.schema_version != CLIENT_PREFLIGHT_SCHEMA_VERSION
        || manifest.job_id != job_id
        || manifest.display_name.is_empty()
        || manifest.display_name.len() > 256
        || manifest.source.display_name != manifest.display_name
        || !valid_sha256(&manifest.source.sha256)
        || manifest.source.byte_length == 0
        || manifest.metadata.session_id.as_str() != expected_session_id
        || manifest.metadata.mode != SessionMode::Meeting
        || manifest.metadata.origin != SessionOrigin::ImportedFile
        || manifest.metadata.trigger_mode != TriggerMode::Toggle
        || manifest.metadata.locale_hint_bcp47.is_some()
        || !manifest.metadata.preferred_languages_bcp47.is_empty()
        || manifest.metadata.retention_expires_at_utc.is_none()
        || manifest.metadata.privacy_policy_version != "development-only"
        || OwnerNamespace::try_from(manifest.owner_namespace.clone()).is_err()
        || manifest.tracks.len() != 1
        || manifest.tracks[0].track_id != "track-1"
        || manifest.tracks[0].source
            != serde_json::json!({"kind": "imported", "provenance": "unknown"})
        || manifest.tracks[0].device_id.is_some()
        || manifest.tracks[0].original_sample_rate_hz != 16_000
        || manifest.tracks[0].original_channels != 1
        || manifest.chunks.is_empty()
        || manifest.chunks.len() > 4_096
    {
        return Err("client preflight manifest is outside its structural contract".into());
    }
    let mut next_sample = 0_u64;
    let mut next_start_ms = 0_u64;
    for chunk in &manifest.chunks {
        let reference = &chunk.reference;
        let expected_filename = format!(
            "track-1-{}-{}.pcm",
            reference.replay_key.sequence_start, reference.replay_key.sequence_end
        );
        let sample_count = reference
            .replay_key
            .sequence_end
            .checked_sub(reference.replay_key.sequence_start)
            .and_then(|value| value.checked_add(1))
            .ok_or_else(|| "client preflight chunk range is invalid".to_string())?;
        if reference.replay_key.schema_version != 1
            || reference.replay_key.session_id != expected_session_id
            || reference.replay_key.track_id != "track-1"
            || reference.replay_key.sequence_start != next_sample
            || reference.content_identity.byte_length != sample_count.saturating_mul(2)
            || reference.content_identity.byte_length == 0
            || reference.content_identity.byte_length > 1024 * 1024
            || !valid_sha256(&reference.content_identity.sha256)
            || reference.audio_codec != "pcm_s16le"
            || reference.sample_rate_hz != 16_000
            || reference.channels != 1
            || reference.start_ms != next_start_ms
            || u64::from(reference.duration_ms).saturating_mul(16) != sample_count
            || chunk.filename != expected_filename
        {
            return Err("client preflight chunk declaration is inconsistent".into());
        }
        next_sample = reference
            .replay_key
            .sequence_end
            .checked_add(1)
            .ok_or_else(|| "client preflight chunk range overflowed".to_string())?;
        next_start_ms = next_start_ms
            .checked_add(u64::from(reference.duration_ms))
            .ok_or_else(|| "client preflight timeline overflowed".to_string())?;
    }
    let normalization = manifest.preprocessing.normalization();
    if normalization.stage_input_sha256() != manifest.source.sha256
        || normalization.source_sample_count() == 0
        || normalization.source_sample_count() > next_sample
        || !manifest
            .preprocessing
            .is_valid_for_output_samples(next_sample)
    {
        return Err("client preflight preprocessing evidence is inconsistent".into());
    }
    Ok(())
}

fn read_probe_pcm(
    manifest: &ImportedClientPreflightManifest,
    spool_root: &Path,
    window: &LidProbeWindow,
) -> Result<Vec<u8>, String> {
    let expected_bytes = window
        .sample_count()
        .checked_mul(2)
        .and_then(|value| usize::try_from(value).ok())
        .ok_or_else(|| "LID probe length is out of range".to_string())?;
    let mut output = Vec::with_capacity(expected_bytes);
    let job_directory = spool_root.join(&manifest.job_id);
    for chunk in &manifest.chunks {
        let chunk_start = chunk.reference.replay_key.sequence_start;
        let chunk_end = chunk
            .reference
            .replay_key
            .sequence_end
            .checked_add(1)
            .ok_or_else(|| "client preflight chunk range overflowed".to_string())?;
        let overlap_start = chunk_start.max(window.source_start_sample());
        let overlap_end = chunk_end.min(window.source_end_sample());
        if overlap_start >= overlap_end {
            continue;
        }
        let body = super::chunk::read_prepared_chunk(
            &job_directory.join(&chunk.filename),
            spool_root,
            &chunk.reference,
        )?;
        let byte_start = usize::try_from((overlap_start - chunk_start).saturating_mul(2))
            .map_err(|_| "LID probe offset is out of range")?;
        let byte_end = usize::try_from((overlap_end - chunk_start).saturating_mul(2))
            .map_err(|_| "LID probe offset is out of range")?;
        let slice = body
            .get(byte_start..byte_end)
            .ok_or_else(|| "LID probe span differs from its prepared chunk".to_string())?;
        output.extend_from_slice(slice);
    }
    if output.len() != expected_bytes {
        return Err("LID probe could not be reconstructed from immutable chunks".into());
    }
    Ok(output)
}

fn write_or_verify_synced(path: &Path, expected: &[u8]) -> Result<(), String> {
    match write_new_synced(path, expected) {
        Ok(()) => Ok(()),
        Err(error) if path.exists() => {
            let metadata = fs::symlink_metadata(path).map_err(|inspect| {
                format!("{error}; failed to inspect existing artifact: {inspect}")
            })?;
            if !metadata.is_file()
                || metadata_is_link_or_reparse(&metadata)
                || metadata.len() != expected.len() as u64
            {
                return Err("existing prepared artifact differs from its declaration".into());
            }
            let mut file = open_no_follow_read(path)
                .map_err(|open| format!("failed to reopen existing prepared artifact: {open}"))?;
            let actual = crate::bounded_file::read_to_end(&mut file, expected.len())
                .map_err(|read| format!("failed to verify existing prepared artifact: {read}"))?;
            if actual != expected {
                return Err("existing prepared artifact differs from its declaration".into());
            }
            Ok(())
        }
        Err(error) => Err(error),
    }
}

fn format_sha256(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn freeze_selected_source(
    source: &mut File,
    destination: &Path,
    expected_bytes: u64,
    ensure_active: &mut impl FnMut() -> Result<(), String>,
) -> Result<File, String> {
    ensure_active()?;
    let source_revision = selected_source_revision(source)?;
    source
        .seek(SeekFrom::Start(0))
        .map_err(|error| format!("failed to seek selected recording for admission: {error}"))?;
    let mut snapshot = create_private_snapshot(destination)?;
    let mut remaining = expected_bytes;
    let mut buffer = [0_u8; 64 * 1024];
    while remaining > 0 {
        ensure_active()?;
        let requested = usize::try_from(remaining.min(buffer.len() as u64))
            .map_err(|_| "selected recording admission length is out of range")?;
        let read = source
            .read(&mut buffer[..requested])
            .map_err(|error| format!("failed to freeze selected recording: {error}"))?;
        if read == 0 {
            return Err("selected recording changed while it was being admitted".into());
        }
        snapshot
            .write_all(&buffer[..read])
            .map_err(|error| format!("failed to write admitted recording snapshot: {error}"))?;
        remaining -= read as u64;
    }
    ensure_active()?;
    let mut trailing = [0_u8; 1];
    if source
        .read(&mut trailing)
        .map_err(|error| format!("failed to verify selected recording admission: {error}"))?
        != 0
    {
        return Err("selected recording changed while it was being admitted".into());
    }
    if selected_source_revision(source)? != source_revision {
        return Err("selected recording changed while it was being admitted".into());
    }
    snapshot
        .flush()
        .map_err(|error| format!("failed to flush admitted recording snapshot: {error}"))?;
    snapshot
        .sync_all()
        .map_err(|error| format!("failed to sync admitted recording snapshot: {error}"))?;
    let metadata = snapshot
        .metadata()
        .map_err(|error| format!("failed to inspect admitted recording snapshot: {error}"))?;
    if !metadata.is_file() || metadata.len() != expected_bytes {
        return Err("admitted recording snapshot has an invalid immutable length".into());
    }
    snapshot
        .seek(SeekFrom::Start(0))
        .map_err(|error| format!("failed to rewind admitted recording snapshot: {error}"))?;
    Ok(snapshot)
}

#[derive(Debug, PartialEq, Eq)]
struct SelectedSourceRevision {
    byte_length: u64,
    modified_at: SystemTime,
}

fn selected_source_revision(source: &File) -> Result<SelectedSourceRevision, String> {
    let metadata = source
        .metadata()
        .map_err(|error| format!("failed to inspect selected recording revision: {error}"))?;
    if !metadata.is_file() {
        return Err("selected recording is not a regular file".into());
    }
    let modified_at = metadata.modified().map_err(|error| {
        format!("failed to inspect selected recording modification time: {error}")
    })?;
    Ok(SelectedSourceRevision {
        byte_length: metadata.len(),
        modified_at,
    })
}

fn create_private_snapshot(path: &Path) -> Result<File, String> {
    let mut options = OpenOptions::new();
    options.read(true).write(true).create_new(true);

    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;

        const FILE_SHARE_READ: u32 = 0x0000_0001;
        options.share_mode(FILE_SHARE_READ);
    }

    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;

        options.mode(0o600);
    }

    options
        .open(path)
        .map_err(|error| format!("failed to reserve admitted recording snapshot: {error}"))
}
