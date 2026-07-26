use sha2::{Digest, Sha256};

use super::{NormalizationEvidence, PreprocessingEvidence, VadComponentEvidence, VadEvidence};

impl VadComponentEvidence {
    pub(crate) fn stage_component_id(&self) -> &str {
        &self.id
    }

    pub(crate) fn stage_component_revision(&self) -> &str {
        &self.revision
    }
}

impl NormalizationEvidence {
    pub(crate) fn stage_input_sha256(&self) -> &str {
        &self.input_source_sha256
    }

    pub(crate) fn stage_output_sha256(&self) -> &str {
        &self.output_pcm_sha256
    }

    pub(crate) fn source_pcm_sha256(&self) -> &str {
        &self.source_pcm_sha256
    }

    pub(crate) fn source_sample_count(&self) -> u64 {
        self.source_sample_count
    }

    pub(crate) fn output_sample_count(&self) -> u64 {
        self.output_sample_count
    }

    pub(crate) fn stage_component_id(&self) -> &str {
        &self.component_id
    }

    pub(crate) fn stage_component_revision(&self) -> &str {
        &self.component_revision
    }

    pub(crate) fn stage_evidence(&self) -> serde_json::Value {
        serde_json::to_value(self).expect("normalization evidence is JSON serializable")
    }
}

impl VadEvidence {
    pub(crate) fn stage_component_id(&self) -> &str {
        self.component.stage_component_id()
    }

    pub(crate) fn stage_component_revision(&self) -> &str {
        self.component.stage_component_revision()
    }

    pub(crate) fn stage_succeeded(&self) -> bool {
        self.status == "complete"
    }

    pub(crate) fn stage_error_code(&self) -> Option<&str> {
        self.error_code.as_deref()
    }

    pub(crate) fn stage_output_sha256(&self) -> String {
        let encoded = serde_json::to_vec(self).expect("VAD evidence is JSON serializable");
        Sha256::digest(encoded)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect()
    }

    pub(crate) fn stage_evidence(&self) -> serde_json::Value {
        serde_json::json!({
            "schemaVersion": 1,
            "status": self.status,
            "intervalCount": self.intervals.len(),
            "errorCode": self.error_code,
            "fullEvidenceSha256": self.stage_output_sha256(),
        })
    }

    pub(crate) fn intervals(&self) -> &[super::SourceVadInterval] {
        &self.intervals
    }
}

impl PreprocessingEvidence {
    pub(crate) fn normalization(&self) -> &NormalizationEvidence {
        &self.normalization
    }

    pub(crate) fn vad(&self) -> &VadEvidence {
        &self.vad
    }
}
