ALTER TABLE recording_jobs
  ADD COLUMN asr_catalog_origin TEXT;

ALTER TABLE recording_jobs
  ADD COLUMN asr_catalog_revision TEXT
  CHECK (
    (
      asr_catalog_origin IS NULL
      AND asr_catalog_revision IS NULL
    )
    OR (
      asr_catalog_origin IS NOT NULL
      AND length(asr_catalog_origin) BETWEEN 1 AND 2048
      AND asr_catalog_revision IS NOT NULL
      AND length(asr_catalog_revision) = 64
      AND asr_catalog_revision NOT GLOB '*[^0-9a-f]*'
    )
  );

CREATE TRIGGER recording_jobs_asr_catalog_binding_frozen_after_remote_attempt
BEFORE UPDATE OF asr_catalog_origin, asr_catalog_revision
ON recording_jobs
FOR EACH ROW
WHEN (
  NEW.asr_catalog_origin IS NOT OLD.asr_catalog_origin
  OR NEW.asr_catalog_revision IS NOT OLD.asr_catalog_revision
) AND EXISTS (
  SELECT 1
  FROM prepared_remote_jobs
  WHERE job_id = OLD.job_id
    AND (create_attempt_base_url IS NOT NULL OR server_job_id IS NOT NULL)
)
BEGIN
  SELECT RAISE(ABORT, 'recording job ASR catalog binding is frozen after remote dispatch');
END;

PRAGMA user_version = 7;
