ALTER TABLE recording_jobs
ADD COLUMN remote_authentication_binding TEXT
CHECK (
    remote_authentication_binding IS NULL
    OR remote_authentication_binding = 'development-loopback'
    OR (
        length(remote_authentication_binding) = 64
        AND remote_authentication_binding NOT GLOB '*[^0-9a-f]*'
    )
);

ALTER TABLE detached_remote_cancellations
ADD COLUMN remote_authentication_binding TEXT
CHECK (
    remote_authentication_binding IS NULL
    OR remote_authentication_binding = 'development-loopback'
    OR (
        length(remote_authentication_binding) = 64
        AND remote_authentication_binding NOT GLOB '*[^0-9a-f]*'
    )
);

UPDATE recording_jobs
SET remote_authority_version = 1
WHERE remote_authority_version = 2
  AND remote_authority_binding IS NOT NULL
  AND remote_authority_binding <> 'development-loopback';

UPDATE detached_remote_cancellations
SET remote_authority_version = 1
WHERE remote_authority_version = 2
  AND remote_authority_binding <> 'development-loopback';

UPDATE recording_jobs
SET remote_authentication_binding = 'development-loopback'
WHERE remote_authority_version = 2
  AND remote_authority_binding = 'development-loopback';

UPDATE detached_remote_cancellations
SET remote_authentication_binding = 'development-loopback'
WHERE remote_authority_version = 2
  AND remote_authority_binding = 'development-loopback';

PRAGMA user_version = 14;
