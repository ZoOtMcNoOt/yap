# Verification Evidence

Evidence records bind implementation/status claims to exact revisions,
commands, environments, and observed boundaries. They must distinguish focused
development checks from a one-time phase/checkpoint gate.

Current architecture-review evidence:

- [Archivist ingestion verification](archivist-ingestion/VERIFICATION.md)
- [Scribe transcript-correction verification](scribe-transcript-correction/VERIFICATION.md)
- [Governed-knowledge maintainability coverage](governed-knowledge-maintainability/COVERAGE.md)
- [Governed-knowledge maintainability findings](governed-knowledge-maintainability/FINDINGS.md)
- [Governed-knowledge maintainability verification](governed-knowledge-maintainability/VERIFICATION.md)
- [Executable ownership findings](executable-ownership-review/FINDINGS.md)
- [Reviewed file inventory](executable-ownership-review/FILE-INVENTORY.md)
- [Checked-head verification](executable-ownership-review/VERIFICATION.md)

Do not commit private scans, scan identifiers, sensitive audio/transcripts, raw
host snapshots, credentials, or enterprise configuration. Public evidence may
record hashes, versions, counts, redacted outcomes, and explicit limitations.
