# Yap Documentation

This index separates current truth, accepted decisions/contracts, active work,
completed evidence, historical rationale, operations, security, and provenance.

If documents disagree, use this priority:

1. executable code, machine-readable contracts, and observed runtime behavior;
2. accepted ADRs and current normative specs;
3. [current status](CURRENT-STATUS.md) and
   [current architecture](architecture/CURRENT-ARCHITECTURE.md);
4. the [long-term Voice OS architecture frame](VOICE-OS-ARCHITECTURE.md) for
   eventual-system intent, subject to accepted ADR precedence;
5. active plans;
6. completed implementation records;
7. archived plans and historical designs.

Unchecked boxes in a completed/archived plan are execution history, not current
backlog.

## Current truth

- [Current status](CURRENT-STATUS.md)
- [Current architecture](architecture/CURRENT-ARCHITECTURE.md)
- [Executable ownership and trust boundaries](architecture/boundaries/EXECUTABLE-OWNERSHIP.md)
- [Roadmap](roadmap/ROADMAP.md)
- [Changelog](../CHANGELOG.md)

## Long-term architecture frame

- [Yap & Voice OS system architecture](VOICE-OS-ARCHITECTURE.md)

This is the first-class readable frame for the eventual Voice OS system. It is
not an archive and must not be silently redefined during cleanup. Executable
behavior, accepted ADRs, current architecture/status, and the ordered roadmap
still control implementation and completion claims.

## Decisions and normative contracts

- [ADR index](adr/README.md)
- [ADR implementation status](ADR-IMPLEMENTATION-STATUS.md)
- [Client state machine](specs/client-state-machine.md)
- [Live dictation client](specs/live-dictation-client-ux.md)
- [Local live fallback](specs/local-live-fallback-sidecar.md)
- [Model download UX](specs/model-download-ux.md)
- [Audio preprocessing contract](specs/local-audio-preprocessing-stack.md)
- [Source-aware diarization](specs/source-aware-diarization.md)
- [Server tier MVP](specs/server-tier-mvp.md)
- [Testing strategy](specs/testing-strategy.md)

The [local LLM sidecar](specs/local-llm-sidecar.md) is an explicitly deferred,
non-normative design draft. It is discoverable for future re-evaluation but is
not current architecture, an active plan, or permission to add a runtime.

`server/openapi/openapi.json` and `server/openapi/live-events.schema.json` are
the normative machine-readable wire contracts. A route in a contract is not an
implementation claim; dynamic server capabilities and executable tests decide
availability.

## Plans

### Active

- [CI actions and cache hardening](plans/active/2026-07-13-ci-actions-cache-hardening.md)
- [VoiceOS/Yap decision, evidence, and future-work queue](plans/active/2026-07-17-voiceos-decision-evidence-queue.md)
- [Integrated MVP validation and delivery control](plans/active/2026-07-23-integrated-mvp-validation-and-delivery-control.md)
- [Phase 10 supervised provider services](plans/active/2026-08-11-phase-10-supervised-provider-services.md)

### Queued

None currently.

### Completed implementation records

- [Governed knowledge ownership and maintainability review](plans/completed/2026-08-10-governed-knowledge-ownership-and-maintainability-review.md)
- [Governed knowledge and agents](plans/completed/2026-08-09-governed-knowledge-and-agents.md)
- [Meeting transcription production qualification](plans/completed/2026-08-03-meeting-transcription-production-qualification.md)
- [Meeting transcription ownership and maintainability review](plans/completed/2026-08-03-meeting-transcription-ownership-and-maintainability-review.md)
- [Tenant-scoped identity and job authorization](plans/completed/2026-07-25-tenant-scoped-identity-and-job-authorization.md)
- [Joint speaker-attributed meeting transcription](plans/completed/2026-07-22-joint-speaker-attributed-meeting-transcription.md)
- [Codebase ownership and maintainability review](plans/completed/2026-07-18-codebase-ownership-and-maintainability-review.md)
- [Local Nemotron live transcription](plans/completed/2026-07-05-local-nemotron-live-transcription.md)
- [Model download UX](plans/completed/2026-07-08-model-download-ux.md)
- [Phase 3 server contract and durable connector](plans/completed/2026-07-10-server-contract-durable-connector.md)
- [Private ASR node](plans/completed/2026-07-13-private-asr-node.md)
- [Remote recording transcription](plans/completed/2026-07-14-remote-recording-transcription.md)
- [Executable ownership and maintainability review](plans/completed/2026-07-15-executable-ownership-and-maintainability-review.md)
- [Audio preprocessing and language routing](plans/completed/2026-07-16-audio-preprocessing-and-language-routing.md)

### Archived plans and historical designs

The [plans index](plans/README.md) defines lifecycle rules. Superseded recipes
live under [plans/archived](plans/archived/). Retired design snapshots live
under [archive/historical-designs](archive/historical-designs/).
They preserve rationale and provenance but are not current implementation
instructions. Detailed historical task reports live under
[archive/implementation-evidence](archive/implementation-evidence/); see the
[archive index](archive/README.md).

## Operations, research, security, and provenance

- [Server-node setup](runbooks/yap-server-node-setup.md)
- [Provider supervisor service](runbooks/provider-supervisor-service.md)
- [Agent admission service](runbooks/agent-admission-service.md)
- [Dependency audit policy](runbooks/dependency-audit-policy.md)
- [Repository housekeeping](runbooks/repo-housekeeping.md)
- [Target-client language-routing qualification](runbooks/target-client-language-routing-qualification.md)
- [Integrated product checkpoint gate](runbooks/integrated-product-checkpoint-gate.md)
- [Meeting-transcription maintainability checkpoint](runbooks/meeting-transcription-maintainability-checkpoint.md)
- [Integrated identity and access gate](runbooks/integrated-identity-access-gate.md)
- [Phase 9 governed-knowledge gate command and private-evidence boundary](../server/README.md#governed-knowledge-candidate-and-complete-gate)
- [Historical Phase 6 preprocessing and language-routing gate](runbooks/integrated-preprocessing-language-routing-gate.md)
- [Independent transcript-reference review](runbooks/independent-transcript-reference-review.md)
- [Research index](research/README.md)
- [Public security posture](security/SECURITY-POSTURE.md)
- [Third-party provenance](provenance/THIRD-PARTY.md)

## Verification evidence

- [Evidence policy and index](evidence/README.md)
- [Executable ownership findings](evidence/executable-ownership-review/FINDINGS.md)
- [Reviewed file inventory](evidence/executable-ownership-review/FILE-INVENTORY.md)
- [Checked-head verification](evidence/executable-ownership-review/VERIFICATION.md)

Private scans, scan identifiers, sensitive audio/transcript data, host paths,
and raw machine evidence do not belong in this documentation tree, PRs, CI
logs, or tracked test results.
