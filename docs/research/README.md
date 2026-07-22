# Research audits

Research audits pin external references and compare them with the current Yap
implementation. They are non-normative: ADRs still own architectural decisions,
and executable code/tests still own implementation truth.

An audit must distinguish three states:

- **Studied:** behavior or architecture was inspected; no donor source ships.
- **Adapted:** donor source influenced a Yap implementation and requires exact
  file-level provenance plus the applicable notice.
- **Copied:** donor source is substantially retained and requires exact
  file-level provenance, license compliance, modification notices, and tests.

Do not add a studied donor to `THIRD_PARTY_PROVENANCE.json`. Add it only when
adapted or copied source enters a shipped artifact, then update
`THIRD_PARTY_NOTICES.md` and the release-contract evidence in the same change.

## Audits

| Audit | Decision |
|-------|----------|
| [Freeflow and Meetily donor audit](2026-07-12-freeflow-meetily-reuse-audit.md) | Preserve Yap's runtime/safety core; selectively adapt donor behaviors after parity, security, license, and native tests |
| [GB10 readiness audit](2026-07-12-gb10-readiness-audit.md) | Start Phase 3 loopback-only over the private-Ethernet SSH tunnel; the host is multi-homed and ASR remains unprovisioned |
| [ASR serving runtime evaluation](2026-07-14-asr-serving-runtime-evaluation.md) | Keep the pinned raw Transformers/BF16 worker as the executable baseline; benchmark NVIDIA vLLM only for Cohere, use exact NeMo/Transformers candidates for Nemotron 3.5 on DGX Spark, and record the serving-oriented Nemotron NIM as currently unsupported on that target |
| [Dynamic language detection evaluation](2026-07-16-dynamic-language-detection-evaluation.md) | Phase 6 requires one bounded resident local acoustic-LID/span engine plus offline switching and independent server Nemotron segment tags; native Whisper tiny is the measured but unpromoted footprint baseline, and Qwen3-ASR-1.7B/VibeVoice remain server challengers rather than local language-diarization components |
| [ASR evaluation corpus and runtime qualification](2026-07-17-asr-evaluation-corpus-and-runtime-matrix.md) | Separate natural quality from exact-duration runtime evidence; classify model-specific benchmark exposure; use sealed adjudicated holdouts, rights-locked public comparators, and a machine-validated live/batch/concurrency matrix |
