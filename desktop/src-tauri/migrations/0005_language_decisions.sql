ALTER TABLE recording_jobs
  ADD COLUMN language_mode TEXT NOT NULL DEFAULT 'fixed'
  CHECK (language_mode IN ('fixed', 'dynamic'));

ALTER TABLE recording_jobs
  ADD COLUMN language_bcp47 TEXT DEFAULT 'en-US'
  CHECK (language_bcp47 IS NULL OR (length(language_bcp47) BETWEEN 2 AND 35));

ALTER TABLE recording_jobs
  ADD COLUMN language_disposition TEXT NOT NULL DEFAULT 'legacy_phase5_default'
  CHECK (language_disposition IN (
    'primary', 'manual_override', 'detected_suggestion_confirmed',
    'explicit_dynamic', 'legacy_phase5_default'
  ) AND (
    (
      language_mode = 'fixed'
      AND language_bcp47 IS NOT NULL
      AND language_disposition IN (
        'primary', 'manual_override', 'detected_suggestion_confirmed',
        'legacy_phase5_default'
      )
    )
    OR (
      language_mode = 'dynamic'
      AND language_bcp47 IS NULL
      AND language_disposition = 'explicit_dynamic'
    )
  ));

PRAGMA user_version = 5;
