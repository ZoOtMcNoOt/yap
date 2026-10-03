use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ConnectionCandidate {
    pub(super) schema_version: u16,
    pub(super) source_concept_id: String,
    pub(super) target_concept_id: String,
    pub(super) relationship_type: String,
    pub(super) rationale: String,
}

impl ConnectionCandidate {
    pub(super) fn is_valid(&self) -> bool {
        let identity = |value: &str| {
            !value.is_empty()
                && value.trim() == value
                && value.chars().count() <= 512
                && !value.chars().any(char::is_control)
        };
        self.schema_version == 1
            && identity(&self.source_concept_id)
            && identity(&self.target_concept_id)
            && self.source_concept_id != self.target_concept_id
            && !self.relationship_type.is_empty()
            && self.relationship_type.len() <= 128
            && self.relationship_type.bytes().all(|b| b.is_ascii_graphic())
            && !self.rationale.is_empty()
            && self.rationale.trim() == self.rationale
            && self.rationale.chars().count() <= 2_000
            && !self.rationale.chars().any(|c| c.is_control() && c != '\n')
            && serde_json::to_string(self).is_ok_and(|json| {
                json.chars()
                    .map(|c| if c.is_ascii() { 1 } else { c.len_utf16() * 6 })
                    .sum::<usize>()
                    <= 16_384
            })
    }
}
