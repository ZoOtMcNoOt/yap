mod artifact_io;
mod chunk;
mod decode;
mod language_label_corrections;
mod preparation;
mod preprocessing;
mod result;
mod spool;
mod wav;

pub(super) use chunk::read_prepared_chunk;
pub(crate) use language_label_corrections::{
    append_language_label_correction, read_language_label_review, LanguageLabelCorrectionError,
    LanguageLabelReview,
};
#[cfg(test)]
pub(super) use preparation::prepare_imported_pcm_wav;
pub(super) use preparation::{
    finalize_imported_client_preflight, load_imported_client_preflight,
    prepare_imported_client_preflight_with_cancellation,
    prepare_imported_pcm_wav_with_cancellation, ImportedClientPreflightPreparation,
    ImportedLidPreparation, ImportedPcmWavPreparation,
};
pub(super) use result::{publish_remote_result, read_published_remote_transcript};
pub(super) use spool::reset_unattached_spool;

#[cfg(test)]
use result::validate_published_result_contract;
#[cfg(test)]
use wav::{validate_pcm_data_bytes, MAX_WAV_CONTAINER_OVERHEAD_BYTES};

#[cfg(test)]
mod client_preprocessing_qualification;
#[cfg(test)]
mod tests;
