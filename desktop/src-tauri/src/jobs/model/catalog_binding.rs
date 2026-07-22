const MAX_CATALOG_ORIGIN_BYTES: usize = 2_048;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AsrCatalogBinding {
    pub(crate) origin: String,
    pub(crate) catalog_revision: String,
}

impl AsrCatalogBinding {
    /// Constructs immutable evidence identifying the capability catalog used
    /// to admit a server-batch job.
    ///
    /// The constructor is public because `NewRecordingJob` is a public
    /// persistence boundary. Callers must not be able to create a
    /// server-batch record without first validating the catalog origin and
    /// revision that record freezes.
    pub fn try_new(origin: String, catalog_revision: String) -> Result<Self, &'static str> {
        if origin.is_empty()
            || origin.len() > MAX_CATALOG_ORIGIN_BYTES
            || origin
                .bytes()
                .any(|byte| byte.is_ascii_control() || !byte.is_ascii())
        {
            return Err("ASR catalog origin is outside the durable contract");
        }
        if catalog_revision.len() != 64
            || !catalog_revision
                .bytes()
                .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
        {
            return Err("ASR catalog revision must be a lowercase SHA-256 digest");
        }
        Ok(Self {
            origin,
            catalog_revision,
        })
    }

    pub fn origin(&self) -> &str {
        &self.origin
    }

    pub fn catalog_revision(&self) -> &str {
        &self.catalog_revision
    }

    #[cfg(test)]
    pub(crate) fn for_test() -> Self {
        Self::try_new("http://127.0.0.1:18765".into(), "a".repeat(64))
            .expect("test ASR catalog binding is valid")
    }
}
