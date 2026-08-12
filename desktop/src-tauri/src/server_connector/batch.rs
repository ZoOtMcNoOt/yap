mod client;
mod error;
mod preprocessing;
mod request;
mod response;
mod result_contract;
mod validation;

pub(crate) use client::{validate_batch_base_url, BatchApiClient};
pub(crate) use error::BatchClientError;
pub(crate) use preprocessing::{
    validate_vad_intervals, DecodedSourceEvidence, NormalizationEvidence, PreprocessingEvidence,
    SourceVadInterval, VadComponentEvidence, VadEvidence, MAX_VAD_INTERVALS,
};
pub(crate) use request::{
    CaptureChunkReference, CaptureManifestReference, CommitRecordingJobRequest, ContentIdentity,
    CreateRecordingJobRequest, RetryServerStageRequest, ServerReplayKey, UploadTrack,
};
#[cfg(test)]
pub(crate) use response::{
    AlignedWord, AlignedWordAttribution, AlignmentOutcome, AlignmentUnavailableReason,
    LanguageDecision, LanguageSegment, LanguageSegmentReason, ModelRevision,
    ServerLanguageSpanEvidence,
};
pub(crate) use response::{
    AlignmentStatus, AnonymousSpeakerAttribution, ApiError, ChunkUploadReceipt,
    LanguageSegmentStatus, RecordingJob, ServerStageName, ServerStageProjectionEnvelope,
    ServerStageState, SpeakerResultRevision, TranscriptResultRevision, MAX_SPEAKER_RESULT_BYTES,
    MAX_TRANSCRIPT_RESULT_BYTES,
};
pub(crate) use result_contract::{
    validate_speaker_result_for_recording, validate_transcript_result_for_recording,
};

#[cfg(test)]
mod tests;
