CREATE TABLE recording_jobs (
  job_id TEXT PRIMARY KEY,
  session_mode TEXT NOT NULL CHECK (session_mode IN ('dictation', 'meeting')),
  session_origin TEXT NOT NULL CHECK (
    session_origin IN ('live_capture', 'imported_file')
  ),
  source_path TEXT,
  source_ownership TEXT NOT NULL DEFAULT 'external' CHECK (
    source_ownership IN ('external', 'yap_spool')
  ),
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
  cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK (
    cancellation_requested IN (0, 1)
  ),
  capture_commit_path TEXT,
  capture_manifest_sha256 TEXT,
  error_code TEXT,
  error_message TEXT,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  expires_at_ms INTEGER,
  language_mode TEXT NOT NULL DEFAULT 'fixed' CHECK (
    language_mode IN ('fixed', 'dynamic')
  ),
  language_bcp47 TEXT DEFAULT 'en-US' CHECK (
    language_bcp47 IS NULL OR length(language_bcp47) BETWEEN 2 AND 35
  ),
  language_disposition TEXT NOT NULL DEFAULT 'primary' CHECK (
    language_disposition IN (
      'primary', 'manual_override', 'detected_suggestion_confirmed',
      'explicit_dynamic'
    )
    AND (
      (
        language_mode = 'fixed'
        AND language_bcp47 IS NOT NULL
        AND language_disposition IN (
          'primary', 'manual_override', 'detected_suggestion_confirmed'
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
  asr_catalog_revision TEXT CHECK (
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
  language_decision_locked INTEGER NOT NULL DEFAULT 1 CHECK (
    language_decision_locked IN (0, 1)
  ),
  client_stage_history_complete INTEGER NOT NULL DEFAULT 0 CHECK (
    client_stage_history_complete IN (0, 1)
  ),
  remote_authority_binding TEXT CHECK (
    remote_authority_binding IS NULL
    OR remote_authority_binding = 'development-loopback'
    OR (
      length(remote_authority_binding) = 64
      AND remote_authority_binding NOT GLOB '*[^0-9a-f]*'
    )
  ),
  remote_authority_version INTEGER NOT NULL DEFAULT 2 CHECK (
    remote_authority_version = 2
  ),
  remote_authentication_binding TEXT CHECK (
    remote_authentication_binding IS NULL
    OR remote_authentication_binding = 'development-loopback'
    OR (
      length(remote_authentication_binding) = 64
      AND remote_authentication_binding NOT GLOB '*[^0-9a-f]*'
    )
  ),
  CHECK (session_origin = 'live_capture' OR source_path IS NOT NULL)
);

CREATE TABLE prepared_remote_jobs (
  job_id TEXT PRIMARY KEY REFERENCES recording_jobs(job_id) ON DELETE CASCADE,
  create_request_json TEXT NOT NULL CHECK (
    length(create_request_json) BETWEEN 2 AND 1048576
  ),
  capture_manifest_path TEXT NOT NULL,
  capture_manifest_sha256 TEXT NOT NULL CHECK (
    length(capture_manifest_sha256) = 64
    AND capture_manifest_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  server_job_id TEXT UNIQUE,
  server_base_url TEXT,
  server_cancellation_acknowledged_at_ms INTEGER CHECK (
    server_cancellation_acknowledged_at_ms IS NULL
    OR server_cancellation_acknowledged_at_ms >= 0
  ),
  create_attempt_base_url TEXT CHECK (
    create_attempt_base_url IS NULL
    OR length(create_attempt_base_url) BETWEEN 1 AND 2048
  ),
  CHECK (
    (server_job_id IS NULL AND server_base_url IS NULL)
    OR (server_job_id IS NOT NULL AND server_base_url IS NOT NULL)
  )
);

CREATE TABLE job_chunks (
  job_id TEXT NOT NULL REFERENCES recording_jobs(job_id) ON DELETE CASCADE,
  owner_namespace TEXT NOT NULL,
  session_id TEXT NOT NULL,
  track_id TEXT NOT NULL,
  sequence_start INTEGER NOT NULL,
  sequence_end INTEGER NOT NULL,
  content_sha256 TEXT NOT NULL,
  artifact_path TEXT NOT NULL,
  upload_offset INTEGER NOT NULL DEFAULT 0,
  acknowledged_object_id TEXT,
  acknowledged_at_ms INTEGER,
  content_byte_length INTEGER NOT NULL DEFAULT 0 CHECK (
    content_byte_length >= 0
  ),
  PRIMARY KEY (job_id, track_id, sequence_start, sequence_end),
  CHECK (sequence_end >= sequence_start),
  CHECK (upload_offset >= 0)
);

CREATE TABLE remote_spool_cleanup (
  job_id TEXT PRIMARY KEY CHECK (
    length(job_id) BETWEEN 1 AND 128
    AND job_id NOT GLOB '*[^A-Za-z0-9_-]*'
  ),
  queued_at_ms INTEGER NOT NULL CHECK (queued_at_ms >= 0)
);

CREATE TABLE detached_remote_cancellations (
  server_base_url TEXT NOT NULL CHECK (
    length(server_base_url) BETWEEN 1 AND 2048
  ),
  server_job_id TEXT NOT NULL CHECK (
    length(server_job_id) BETWEEN 1 AND 128
    AND server_job_id NOT GLOB '*[^A-Za-z0-9_-]*'
  ),
  create_request_json TEXT NOT NULL CHECK (
    length(create_request_json) BETWEEN 2 AND 1048576
  ),
  queued_at_ms INTEGER NOT NULL CHECK (queued_at_ms >= 0),
  remote_authority_binding TEXT NOT NULL DEFAULT 'development-loopback' CHECK (
    remote_authority_binding = 'development-loopback'
    OR (
      length(remote_authority_binding) = 64
      AND remote_authority_binding NOT GLOB '*[^0-9a-f]*'
    )
  ),
  remote_authority_version INTEGER NOT NULL DEFAULT 2 CHECK (
    remote_authority_version = 2
  ),
  remote_authentication_binding TEXT CHECK (
    remote_authentication_binding IS NULL
    OR remote_authentication_binding = 'development-loopback'
    OR (
      length(remote_authentication_binding) = 64
      AND remote_authentication_binding NOT GLOB '*[^0-9a-f]*'
    )
  ),
  PRIMARY KEY (server_base_url, server_job_id)
);

CREATE TABLE job_ledger_write_probe (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  generation INTEGER NOT NULL CHECK (generation >= 0)
);

INSERT INTO job_ledger_write_probe (singleton, generation) VALUES (1, 0);

CREATE TABLE job_stage_attempts (
  job_id TEXT NOT NULL REFERENCES recording_jobs(job_id) ON DELETE CASCADE,
  stage TEXT NOT NULL CHECK (stage IN (
    'normalization', 'vad', 'lid_preflight', 'user_confirmation'
  )),
  attempt INTEGER NOT NULL CHECK (attempt BETWEEN 1 AND 64),
  state TEXT NOT NULL CHECK (state IN (
    'running', 'succeeded', 'unavailable', 'failed', 'cancelled'
  )),
  input_fingerprint_sha256 TEXT NOT NULL CHECK (
    length(input_fingerprint_sha256) = 64
  ),
  output_fingerprint_sha256 TEXT CHECK (
    output_fingerprint_sha256 IS NULL
    OR length(output_fingerprint_sha256) = 64
  ),
  component_id TEXT NOT NULL CHECK (length(component_id) BETWEEN 1 AND 128),
  component_revision TEXT NOT NULL CHECK (
    length(component_revision) BETWEEN 1 AND 128
  ),
  started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
  completed_at_ms INTEGER CHECK (
    completed_at_ms IS NULL OR completed_at_ms >= started_at_ms
  ),
  retryable INTEGER CHECK (retryable IS NULL OR retryable IN (0, 1)),
  reason TEXT CHECK (reason IS NULL OR length(reason) BETWEEN 1 AND 64),
  evidence_json TEXT,
  evidence_sha256 TEXT CHECK (
    evidence_sha256 IS NULL OR length(evidence_sha256) = 64
  ),
  PRIMARY KEY (job_id, stage, attempt),
  CHECK (
    (
      state = 'running'
      AND output_fingerprint_sha256 IS NULL
      AND completed_at_ms IS NULL
      AND retryable IS NULL
      AND reason IS NULL
      AND evidence_json IS NULL
      AND evidence_sha256 IS NULL
    )
    OR (
      state <> 'running'
      AND completed_at_ms IS NOT NULL
      AND retryable IS NOT NULL
      AND (
        (evidence_json IS NULL AND evidence_sha256 IS NULL)
        OR (evidence_json IS NOT NULL AND evidence_sha256 IS NOT NULL)
      )
    )
  )
);

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
    lid_request_id IS NULL
    OR (
      length(lid_request_id) BETWEEN 1 AND 128
      AND lid_request_id NOT GLOB '*[^A-Za-z0-9_-]*'
    )
  ),
  lid_server_base_url TEXT CHECK (
    lid_server_base_url IS NULL
    OR length(lid_server_base_url) BETWEEN 1 AND 2048
  ),
  lid_catalog_revision TEXT CHECK (
    lid_catalog_revision IS NULL
    OR (
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
    (
      lid_request_id IS NULL
      AND lid_server_base_url IS NULL
      AND lid_catalog_revision IS NULL
      AND lid_policy_revision IS NULL
      AND lid_started_at_ms IS NULL
    )
    OR (
      lid_request_id IS NOT NULL
      AND lid_server_base_url IS NOT NULL
      AND lid_catalog_revision IS NOT NULL
      AND lid_policy_revision IS NOT NULL
      AND lid_started_at_ms IS NOT NULL
    )
  )
);

CREATE INDEX recording_jobs_status_retry_idx
  ON recording_jobs(status, next_attempt_at_ms, created_at_ms);

CREATE INDEX job_stage_attempts_job_stage_idx
  ON job_stage_attempts(job_id, stage, attempt);

CREATE TRIGGER recording_jobs_language_decision_cannot_unlock
BEFORE UPDATE OF language_decision_locked
ON recording_jobs
FOR EACH ROW
WHEN OLD.language_decision_locked = 1 AND NEW.language_decision_locked = 0
BEGIN
  SELECT RAISE(ABORT, 'recording job language decision cannot be unlocked');
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

PRAGMA application_id = 1497452618;
PRAGMA user_version = 1;
