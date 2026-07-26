CREATE TRIGGER recording_jobs_language_decision_immutable
BEFORE UPDATE OF language_mode, language_bcp47, language_disposition
ON recording_jobs
FOR EACH ROW
WHEN NEW.language_mode IS NOT OLD.language_mode
  OR NEW.language_bcp47 IS NOT OLD.language_bcp47
  OR NEW.language_disposition IS NOT OLD.language_disposition
BEGIN
  SELECT RAISE(ABORT, 'recording job language decision is immutable');
END;

PRAGMA user_version = 6;
