DROP TRIGGER client_preflight_artifact_requires_unlocked_preflight;

CREATE TABLE recording_jobs_rebuilt (
  job_id TEXT PRIMARY KEY,
  session_mode TEXT NOT NULL CHECK (session_mode IN ('dictation', 'meeting')),
  session_origin TEXT NOT NULL CHECK (session_origin IN ('live_capture', 'imported_file')),
  source_path TEXT,
  source_ownership TEXT NOT NULL DEFAULT 'external'
    CHECK (source_ownership IN ('external', 'yap_spool')),
  output_path TEXT,
  display_name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN (
    'accepted', 'preflighting', 'blocked_setup_required',
    'blocked_server_unavailable', 'blocked_sign_in_required',
    'queued_local_fallback', 'queued_server', 'preprocessing',
    'uploading', 'server_processing', 'local_transcribing', 'saving',
    'diarization_queued', 'diarization_running', 'complete', 'partial',
    'failed', 'cancelled'
  )),
  route TEXT CHECK (
    route IS NULL OR route IN ('local_fallback', 'server_batch', 'server_live')
  ),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  next_attempt_at_ms INTEGER,
  cancellation_requested INTEGER NOT NULL DEFAULT 0
    CHECK (cancellation_requested IN (0, 1)),
  capture_commit_path TEXT,
  capture_manifest_sha256 TEXT,
  error_code TEXT,
  error_message TEXT,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  expires_at_ms INTEGER,
  language_mode TEXT NOT NULL DEFAULT 'fixed'
    CHECK (language_mode IN ('fixed', 'dynamic')),
  language_bcp47 TEXT DEFAULT 'en-US'
    CHECK (language_bcp47 IS NULL OR length(language_bcp47) BETWEEN 2 AND 35),
  language_disposition TEXT NOT NULL DEFAULT 'legacy_implicit_english_default'
    CHECK (
      language_disposition IN (
        'primary', 'manual_override', 'detected_suggestion_confirmed',
        'explicit_dynamic', 'legacy_implicit_english_default'
      )
      AND (
        (
          language_mode = 'fixed'
          AND language_bcp47 IS NOT NULL
          AND language_disposition IN (
            'primary', 'manual_override', 'detected_suggestion_confirmed',
            'legacy_implicit_english_default'
          )
        )
        OR (
          language_mode = 'dynamic'
          AND language_bcp47 IS NULL
          AND language_disposition = 'explicit_dynamic'
        )
      )
    ),
  asr_catalog_origin TEXT,
  asr_catalog_revision TEXT
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
    ),
  language_decision_locked INTEGER NOT NULL DEFAULT 1
    CHECK (language_decision_locked IN (0, 1)),
  client_stage_history_complete INTEGER NOT NULL DEFAULT 0
    CHECK (client_stage_history_complete IN (0, 1)),
  CHECK (session_origin = 'live_capture' OR source_path IS NOT NULL)
);

INSERT INTO recording_jobs_rebuilt (
  job_id,
  session_mode,
  session_origin,
  source_path,
  source_ownership,
  output_path,
  display_name,
  status,
  route,
  attempt_count,
  next_attempt_at_ms,
  cancellation_requested,
  capture_commit_path,
  capture_manifest_sha256,
  error_code,
  error_message,
  created_at_ms,
  updated_at_ms,
  expires_at_ms,
  language_mode,
  language_bcp47,
  language_disposition,
  asr_catalog_origin,
  asr_catalog_revision,
  language_decision_locked,
  client_stage_history_complete
)
SELECT
  job_id,
  session_mode,
  session_origin,
  source_path,
  source_ownership,
  output_path,
  display_name,
  status,
  route,
  attempt_count,
  next_attempt_at_ms,
  cancellation_requested,
  capture_commit_path,
  capture_manifest_sha256,
  error_code,
  error_message,
  created_at_ms,
  updated_at_ms,
  expires_at_ms,
  language_mode,
  language_bcp47,
  CASE language_disposition
    WHEN 'legacy_phase5_default' THEN 'legacy_implicit_english_default'
    ELSE language_disposition
  END,
  asr_catalog_origin,
  asr_catalog_revision,
  language_decision_locked,
  client_stage_history_complete
FROM recording_jobs;

DROP TABLE recording_jobs;
ALTER TABLE recording_jobs_rebuilt RENAME TO recording_jobs;

CREATE INDEX recording_jobs_status_retry_idx
  ON recording_jobs(status, next_attempt_at_ms, created_at_ms);

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

CREATE TRIGGER recording_jobs_language_decision_confirmed_update
BEFORE UPDATE OF language_mode, language_bcp47, language_disposition
ON recording_jobs
FOR EACH ROW
WHEN NEW.language_mode IS NOT OLD.language_mode
  OR NEW.language_bcp47 IS NOT OLD.language_bcp47
  OR NEW.language_disposition IS NOT OLD.language_disposition
BEGIN
  SELECT CASE
    WHEN OLD.language_decision_locked <> 0 OR NEW.language_decision_locked <> 1
    THEN RAISE(ABORT, 'recording job language decision requires atomic confirmation')
  END;
END;

CREATE TRIGGER recording_jobs_language_decision_cannot_unlock
BEFORE UPDATE OF language_decision_locked
ON recording_jobs
FOR EACH ROW
WHEN OLD.language_decision_locked = 1 AND NEW.language_decision_locked = 0
BEGIN
  SELECT RAISE(ABORT, 'recording job language decision cannot be unlocked');
END;

CREATE TRIGGER recording_jobs_language_decision_lock_requires_confirmation
BEFORE UPDATE OF language_decision_locked
ON recording_jobs
FOR EACH ROW
WHEN OLD.language_decision_locked = 0 AND NEW.language_decision_locked = 1
BEGIN
  SELECT CASE
    WHEN NOT EXISTS (
      SELECT 1
      FROM job_stage_attempts
      WHERE job_id = OLD.job_id
        AND stage = 'user_confirmation'
        AND state = 'succeeded'
    )
    THEN RAISE(ABORT, 'recording job language decision requires confirmed stage evidence')
  END;
END;

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

PRAGMA user_version = 11;
