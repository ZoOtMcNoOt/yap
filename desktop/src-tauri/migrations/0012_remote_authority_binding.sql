ALTER TABLE recording_jobs
ADD COLUMN remote_authority_binding TEXT
CHECK (
    remote_authority_binding IS NULL
    OR remote_authority_binding = 'development-loopback'
    OR (
        length(remote_authority_binding) = 64
        AND remote_authority_binding NOT GLOB '*[^0-9a-f]*'
    )
);

UPDATE recording_jobs
SET remote_authority_binding = 'development-loopback'
WHERE route = 'server_batch';

ALTER TABLE detached_remote_cancellations
ADD COLUMN remote_authority_binding TEXT NOT NULL DEFAULT 'development-loopback'
CHECK (
    remote_authority_binding = 'development-loopback'
    OR (
        length(remote_authority_binding) = 64
        AND remote_authority_binding NOT GLOB '*[^0-9a-f]*'
    )
);

PRAGMA user_version = 12;
