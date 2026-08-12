use sha2::{Digest, Sha256};

const MAXIMUM_SEGMENTS: usize = 64;
const MAXIMUM_SOURCE_CHARACTERS: usize = 32_768;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct FinalizedTranscriptSegment {
    pub(crate) text: String,
    pub(crate) start_ms: u64,
    pub(crate) end_ms: u64,
    pub(crate) language_bcp47: String,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct SourceBoundTranscriptSegment {
    pub(crate) segment_id: String,
    pub(crate) start_character: usize,
    pub(crate) end_character: usize,
    pub(crate) start_milliseconds: u64,
    pub(crate) end_milliseconds: u64,
    pub(crate) language_bcp47: String,
    pub(crate) text: String,
    pub(crate) text_sha256: String,
}

pub(crate) fn bind_finalized_transcript_segments(
    transcript: &str,
    finalized: &[FinalizedTranscriptSegment],
) -> Result<Vec<SourceBoundTranscriptSegment>, String> {
    if finalized.is_empty() {
        return Ok(Vec::new());
    }
    if finalized.len() > MAXIMUM_SEGMENTS
        || transcript.is_empty()
        || transcript.chars().count() > MAXIMUM_SOURCE_CHARACTERS
    {
        return Err("finalized transcript segments exceed the correction boundary".into());
    }

    let cleaned = finalized
        .iter()
        .map(|segment| crate::live::recordings::clean_transcript_text(&segment.text))
        .collect::<Vec<_>>();
    if cleaned.iter().any(String::is_empty) || cleaned.join(" ") != transcript {
        return Err("finalized transcript segments do not cover the saved transcript".into());
    }

    let mut result = Vec::with_capacity(finalized.len());
    let mut start_character = 0_usize;
    let mut prior_end_ms = None;
    for (index, (source, cleaned)) in finalized.iter().zip(cleaned).enumerate() {
        if source.end_ms <= source.start_ms
            || prior_end_ms.is_some_and(|prior| source.start_ms < prior)
            || !valid_language(&source.language_bcp47)
        {
            return Err("finalized transcript segment timing or language is invalid".into());
        }
        let text = if index == 0 {
            cleaned
        } else {
            format!(" {cleaned}")
        };
        let characters = text.chars().count();
        let end_character = start_character
            .checked_add(characters)
            .ok_or_else(|| "finalized transcript character span overflowed".to_string())?;
        result.push(SourceBoundTranscriptSegment {
            segment_id: format!("segment-{:04}", index + 1),
            start_character,
            end_character,
            start_milliseconds: source.start_ms,
            end_milliseconds: source.end_ms,
            language_bcp47: source.language_bcp47.clone(),
            text_sha256: sha256_text(&text),
            text,
        });
        start_character = end_character;
        prior_end_ms = Some(source.end_ms);
    }
    validate_source_bound_transcript_segments(transcript, &result)?;
    Ok(result)
}

pub(crate) fn validate_source_bound_transcript_segments(
    transcript: &str,
    segments: &[SourceBoundTranscriptSegment],
) -> Result<(), String> {
    if segments.is_empty()
        || segments.len() > MAXIMUM_SEGMENTS
        || transcript.is_empty()
        || transcript.chars().count() > MAXIMUM_SOURCE_CHARACTERS
    {
        return Err("transcript correction segment set is invalid".into());
    }
    let mut expected_character = 0_usize;
    let mut prior_end_ms = None;
    let mut source = String::new();
    for (index, segment) in segments.iter().enumerate() {
        if segment.segment_id != format!("segment-{:04}", index + 1)
            || segment.start_character != expected_character
            || segment.end_character <= segment.start_character
            || segment.end_character - segment.start_character != segment.text.chars().count()
            || segment.text.is_empty()
            || segment.text.contains('\0')
            || segment.start_milliseconds >= segment.end_milliseconds
            || prior_end_ms.is_some_and(|prior| segment.start_milliseconds < prior)
            || !valid_language(&segment.language_bcp47)
            || sha256_text(&segment.text) != segment.text_sha256
        {
            return Err("transcript correction segment identity differs".into());
        }
        expected_character = segment.end_character;
        prior_end_ms = Some(segment.end_milliseconds);
        source.push_str(&segment.text);
    }
    if source != transcript {
        return Err("transcript correction segments do not cover the source".into());
    }
    Ok(())
}

pub(crate) fn sha256_text(value: &str) -> String {
    Sha256::digest(value.as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn valid_language(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 35
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finalized_segments_bind_exact_clean_text_hashes_and_timing() {
        let segments = bind_finalized_transcript_segments(
            "NASA called. Thank you.",
            &[
                FinalizedTranscriptSegment {
                    text: "NASA called.".into(),
                    start_ms: 80,
                    end_ms: 480,
                    language_bcp47: "en-US".into(),
                },
                FinalizedTranscriptSegment {
                    text: "  THank   you.. ".into(),
                    start_ms: 600,
                    end_ms: 1_100,
                    language_bcp47: "en-US".into(),
                },
            ],
        )
        .unwrap();

        assert_eq!(segments.len(), 2);
        assert_eq!(segments[1].text, " Thank you.");
        assert_eq!(segments[1].start_character, 12);
        assert_eq!(segments[1].start_milliseconds, 600);
        assert_eq!(segments[1].text_sha256, sha256_text(" Thank you."));
    }

    #[test]
    fn finalized_segments_reject_gaps_overlap_and_text_drift() {
        let segment = FinalizedTranscriptSegment {
            text: "hello".into(),
            start_ms: 10,
            end_ms: 20,
            language_bcp47: "en-US".into(),
        };
        assert!(
            bind_finalized_transcript_segments("different", std::slice::from_ref(&segment))
                .is_err()
        );
        let mut overlap = segment.clone();
        overlap.start_ms = 19;
        overlap.end_ms = 30;
        assert!(bind_finalized_transcript_segments("hello hello", &[segment, overlap]).is_err());
    }
}
