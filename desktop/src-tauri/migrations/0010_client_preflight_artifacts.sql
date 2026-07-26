CREATE TABLE client_preflight_artifacts (
  job_id TEXT PRIMARY KEY REFERENCES recording_jobs(job_id) ON DELETE CASCADE,
  manifest_path TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL CHECK (
    length(manifest_sha256) = 64
    AND manifest_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  source_pcm_sha256 TEXT NOT NULL CHECK (
    length(source_pcm_sha256) = 64
    AND source_pcm_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  source_sample_count INTEGER NOT NULL CHECK (
    source_sample_count BETWEEN 1 AND 230400000
  ),
  lid_request_id TEXT CHECK (
    lid_request_id IS NULL OR (
      length(lid_request_id) BETWEEN 1 AND 128
      AND lid_request_id NOT GLOB '*[^A-Za-z0-9_-]*'
    )
  ),
  lid_server_base_url TEXT CHECK (
    lid_server_base_url IS NULL OR length(lid_server_base_url) BETWEEN 1 AND 2048
  ),
  lid_catalog_revision TEXT CHECK (
    lid_catalog_revision IS NULL OR (
      length(lid_catalog_revision) = 64
      AND lid_catalog_revision NOT GLOB '*[^0-9a-f]*'
    )
  ),
  lid_policy_revision TEXT CHECK (
    lid_policy_revision IS NULL OR length(lid_policy_revision) BETWEEN 1 AND 128
  ),
  lid_started_at_ms INTEGER CHECK (
    lid_started_at_ms IS NULL OR lid_started_at_ms >= 0
  ),
  CHECK (
    (lid_request_id IS NULL
      AND lid_server_base_url IS NULL
      AND lid_catalog_revision IS NULL
      AND lid_policy_revision IS NULL
      AND lid_started_at_ms IS NULL)
    OR
    (lid_request_id IS NOT NULL
      AND lid_server_base_url IS NOT NULL
      AND lid_catalog_revision IS NOT NULL
      AND lid_policy_revision IS NOT NULL
      AND lid_started_at_ms IS NOT NULL)
  )
);

CREATE TRIGGER client_preflight_artifact_requires_unlocked_preflight
BEFORE INSERT ON client_preflight_artifacts
FOR EACH ROW
BEGIN
  SELECT CASE
    WHEN NOT EXISTS (
      SELECT 1
      FROM recording_jobs
      WHERE job_id = NEW.job_id
        AND status = 'preflighting'
        AND route = 'server_batch'
        AND language_decision_locked = 0
        AND cancellation_requested = 0
    )
    THEN RAISE(ABORT, 'client preflight artifact requires an active unlocked preflight')
  END;
END;

PRAGMA user_version = 10;
