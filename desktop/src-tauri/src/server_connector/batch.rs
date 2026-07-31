mod client;
mod error;
mod preprocessing;
mod request;
mod response;
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
pub(crate) use response::{
    AlignmentStatus, ApiError, ChunkUploadReceipt, LanguageSegmentStatus, RecordingJob,
    ServerStageName, ServerStageProjectionEnvelope, ServerStageState, TranscriptResultRevision,
    MAX_TRANSCRIPT_RESULT_BYTES,
};
#[cfg(test)]
pub(crate) use response::{
    AlignmentUnavailableReason, LanguageDecision, LanguageSegment, LanguageSegmentReason,
    ModelRevision, ServerLanguageSpanEvidence,
};

#[cfg(test)]
mod tests;
