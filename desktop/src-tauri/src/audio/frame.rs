mod chunk;
mod sample;

pub(crate) use chunk::{track_source_matches_origin, validate_current_descriptor};
pub use chunk::{
    AudioChunkEnvelope, AudioCodec, AudioPurpose, AudioRoute, CaptureChunkDescriptor,
    ChunkBuildContext, ChunkReplayKey, ContentIdentity, RetryMetadata, VadSegment,
    CHUNK_SCHEMA_VERSION,
};
pub(crate) use sample::PreparedFramePosition;
pub use sample::{
    AudioFrame, AudioGap, GapCause, ManifestError, PreparedFrame, TrackConfigurationRevision,
};
#[cfg(test)]
mod tests;
