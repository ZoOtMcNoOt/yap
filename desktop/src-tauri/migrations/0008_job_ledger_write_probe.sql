CREATE TABLE job_ledger_write_probe (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  generation INTEGER NOT NULL CHECK (generation >= 0)
);

INSERT INTO job_ledger_write_probe (singleton, generation) VALUES (1, 0);

PRAGMA user_version = 8;
