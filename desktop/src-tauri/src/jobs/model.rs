mod catalog_binding;
mod client_stage;
mod error;
mod language_persistence;
mod records;
mod status;
mod view;

pub use crate::language::{
    RecordingLanguageDecision, RecordingLanguageDisposition, RecordingLanguageMode,
};
pub use catalog_binding::AsrCatalogBinding;
pub use client_stage::{ClientStageAttemptRecord, ClientStageName, ClientStageState};
pub(crate) use client_stage::{ClientStageFinish, ClientStageStart};
pub use error::JobLedgerError;
pub use records::{
    ClientPreflightArtifactRecord, DetachedRemoteCancellationRecord, JobChunkRecord,
    NewClientPreflightArtifact, NewJobChunk, NewPreparedRemoteJob, NewRecordingJob,
    PreparedRemoteJobRecord, RecordingJobRecord,
};
pub use status::{RecordingJobStatus, RecordingRoute, SessionMode, SessionOrigin, SourceOwnership};
pub use view::{RecordingJobView, RecordingLanguageReview, RecordingLanguageReviewKind};

pub(crate) use status::{transition_policy, TransitionPolicy};

#[cfg(test)]
mod tests;
