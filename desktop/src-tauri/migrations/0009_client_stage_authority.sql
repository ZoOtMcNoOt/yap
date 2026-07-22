DROP TRIGGER recording_jobs_language_decision_immutable;

ALTER TABLE recording_jobs
  ADD COLUMN language_decision_locked INTEGER NOT NULL DEFAULT 1
  CHECK (language_decision_locked IN (0, 1));

ALTER TABLE recording_jobs
  ADD COLUMN client_stage_history_complete INTEGER NOT NULL DEFAULT 0
  CHECK (client_stage_history_complete IN (0, 1));

CREATE TABLE job_stage_attempts (
  job_id TEXT NOT NULL REFERENCES recording_jobs(job_id) ON DELETE CASCADE,
  stage TEXT NOT NULL CHECK (stage IN (
    'normalization', 'vad', 'lid_preflight', 'user_confirmation'
  )),
  attempt INTEGER NOT NULL CHECK (attempt BETWEEN 1 AND 64),
  state TEXT NOT NULL CHECK (state IN (
    'running', 'succeeded', 'unavailable', 'failed', 'cancelled'
  )),
  input_fingerprint_sha256 TEXT NOT NULL CHECK (length(input_fingerprint_sha256) = 64),
  output_fingerprint_sha256 TEXT CHECK (
    output_fingerprint_sha256 IS NULL OR length(output_fingerprint_sha256) = 64
  ),
  component_id TEXT NOT NULL CHECK (length(component_id) BETWEEN 1 AND 128),
  component_revision TEXT NOT NULL CHECK (length(component_revision) BETWEEN 1 AND 128),
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

CREATE INDEX job_stage_attempts_job_stage_idx
  ON job_stage_attempts(job_id, stage, attempt);

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

PRAGMA user_version = 9;
