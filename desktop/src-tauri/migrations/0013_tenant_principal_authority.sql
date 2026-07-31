ALTER TABLE recording_jobs
ADD COLUMN remote_authority_version INTEGER NOT NULL DEFAULT 2
CHECK (remote_authority_version IN (1, 2));

UPDATE recording_jobs
SET remote_authority_version = 1
WHERE remote_authority_binding IS NOT NULL
  AND remote_authority_binding <> 'development-loopback';

ALTER TABLE detached_remote_cancellations
ADD COLUMN remote_authority_version INTEGER NOT NULL DEFAULT 2
CHECK (remote_authority_version IN (1, 2));

UPDATE detached_remote_cancellations
SET remote_authority_version = 1
WHERE remote_authority_binding <> 'development-loopback';

PRAGMA user_version = 13;
