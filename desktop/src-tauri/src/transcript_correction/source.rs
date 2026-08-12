use std::path::{Path, PathBuf};

use crate::server_connector::transcript_correction::{sha256_text, TranscriptCorrectionSegment};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum TranscriptCorrectionSourceKind {
    Live,
    Remote,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct TrustedTranscriptCorrectionSource {
    pub(crate) kind: TranscriptCorrectionSourceKind,
    pub(crate) output_path: PathBuf,
    pub(crate) source_revision_sha256: String,
    pub(crate) text: String,
    pub(crate) segments: Vec<TranscriptCorrectionSegment>,
}

pub(crate) fn read_trusted_transcript_correction_source(
    requested: &Path,
) -> Result<TrustedTranscriptCorrectionSource, String> {
    if !requested.is_absolute() {
        return Err("Transcript correction requires an absolute Yap transcript path.".into());
    }
    if crate::live::recordings::is_primary_live_transcript_path(requested) {
        return read_live_source(requested);
    }
    read_remote_source(requested)
}

fn read_live_source(requested: &Path) -> Result<TrustedTranscriptCorrectionSource, String> {
    let recordings = crate::live::recordings::recordings_dir();
    let output_path = crate::live::recordings::canonical_committed_live_path_from_dir(
        requested,
        &recordings,
        true,
    )
    .map_err(|_| "Only committed Yap transcripts can be corrected.".to_string())?;
    let source =
        crate::live::recordings::read_committed_live_transcript_correction_source_from_dir(
            &output_path,
            &recordings,
        )?;
    if source.segments.is_empty() {
        return Err(
            "This raw transcript has no finalized timing evidence and cannot be corrected.".into(),
        );
    }
    let segments = source
        .segments
        .into_iter()
        .map(|segment| {
            TranscriptCorrectionSegment::new(
                segment.segment_id,
                segment.start_character,
                segment.end_character,
                segment.start_milliseconds,
                segment.end_milliseconds,
                segment.language_bcp47,
                segment.text,
                segment.text_sha256,
            )
        })
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| error.to_string())?;
    Ok(TrustedTranscriptCorrectionSource {
        kind: TranscriptCorrectionSourceKind::Live,
        output_path,
        source_revision_sha256: source.source_revision_sha256,
        text: source.text,
        segments,
    })
}

fn read_remote_source(requested: &Path) -> Result<TrustedTranscriptCorrectionSource, String> {
    let source = crate::jobs::read_published_remote_transcript_correction_source(requested)
        .map_err(|_| "Only committed Yap transcripts can be corrected.".to_string())?;
    let characters = source.text.chars().count();
    let segment = TranscriptCorrectionSegment::new(
        "segment-0001".into(),
        0,
        characters,
        source.start_ms,
        source.end_ms,
        source.language_bcp47,
        source.text.clone(),
        sha256_text(&source.text),
    )
    .map_err(|error| error.to_string())?;
    Ok(TrustedTranscriptCorrectionSource {
        kind: TranscriptCorrectionSourceKind::Remote,
        output_path: requested.to_path_buf(),
        source_revision_sha256: source.source_revision_sha256,
        text: source.text,
        segments: vec![segment],
    })
}
