# Yap

Yap is a private, desktop-first transcription system: a Tauri/React client with
an explicit local live fallback and a durable batch path to a private GPU
server.

Phases 1–9 and the post-phase architecture checkpoints are merged. Phase 10 has
also merged the Rust-owned supervised-provider lifecycle, immutable Qwen/Gemma
profiles, bounded already-warm admission, Scribe transcript correction, the
no-LLM Archivist core, and the internal Student learning-question core through
PR #166. Student has no HTTP, native, or renderer surface. Hosted-green head
`593e627b...` passed all 12 required checks, and PR #168 merged the qualified
profile-capacity successor and explicit-submission-only Curator internal core as
`284ab96b...`. PR #169 then merged the privately qualified no-LLM Librarian
core as `d7a7e003...` from hosted head `7505247e...`. Hosted head
`da1127f8...` passed all 12 required checks, and PR #170 merged the qualified
Analyst internal core as `52c45d22...`. Hosted head `53ee0152...` passed all
12 required checks, and PR #171 merged the qualified Coordinator internal core
as `67d836da...`. Exact executable candidate `08b06f6d...` privately qualified
Auditor's idle-only, source-cited review-findings internal core. Hosted head
`937a4129...` passed all 12 required checks, and PR #172 merged Auditor as
`1b255e9a...`. All eight bounded internal role cores are now merged.

Scribe is the only merged product surface. Exact unmerged candidate
`e2ba1864...` adds a Librarian HTTP/native/Knowledge vertical and privately
qualifies its authenticated HTTP server boundary; the native/renderer path is
exact-head public-test green. Hosted review and merge remain pending.
Production identity, simultaneous full-profile residency, sustained capacity,
enterprise deployment, and the remaining role product surfaces stay explicitly
gated.

Start with [current status](docs/CURRENT-STATUS.md). It states what executes,
what is verified, what is still absent, and what happens next.

## Current product boundary

- One installed desktop app owns tray/window lifecycle, native capture,
  deliberate shortcuts, local Nemotron fallback, durable imported jobs,
  connector state, authorized paths, and transcript History.
- One tray-owned island window expands on hover; native code owns its exact
  bounds and visible hit region.
- Imported Phase 5 jobs admit canonical mono PCM16/16 kHz WAV, publish an
  immutable Yap-owned spool, and persist create/upload/commit/status/result/
  cancel progress in native SQLite.
- The active Phase 6 path records deterministic normalization and optional
  explicitly installed/hash-verified Silero source-time evidence without
  deleting source audio; bounded client/server stage attempts survive retry and
  restart.
- The development server binds to numeric loopback. A user-managed SSH forward
  can connect it to the private GB-class node; Yap does not create an external
  application endpoint.
- The merged reference worker uses the digest-pinned NVIDIA PyTorch 26.06 base,
  Python 3.12, the locked NVIDIA Torch/CUDA stack, and transient raw
  Transformers inference. It remains the correctness/rollback baseline rather
  than a persistent serving engine.
- Cohere batch has a digest-pinned NVIDIA vLLM candidate behind the bounded
  worker contract. Nemotron retains its Transformers correctness path and a
  separate resident NeMo finalized-ASR candidate. Their checked launchers keep
  each container on an exact-head internal bridge with no published provider
  port or external egress. Candidate-safety evidence does not itself promote
  either ASR provider.
- The merged team agent plane uses hash-locked Qwen rapid-automation and Gemma
  complex-orchestration vLLM routes with no cross-route fallback. Scribe is the
  only current desktop-facing LLM workflow. Archivist, Student, Curator,
  Librarian, Analyst, Coordinator, and Auditor are bounded merged internal
  cores. The qualified
  profile-capacity successor admits four rapid or eight complex active distinct
  owners on the selected already-warm route, while preserving one active request
  per owner. Analyst's three exact synchronized repeats establish same-warm-
  process batch invariance, not cross-start/global determinism, simultaneous
  residency, sustained capacity, or a production SLO. Coordinator separately
  matched three synchronized eight-owner service waves and returned only
  server-derived, noncanonical, review-required proposal bundles.
  Auditor matched three synchronized eight-owner idle-only service waves,
  returned only server-derived noncanonical review-required findings, and
  proved that active or queued non-idle work blocks it until that work is
  terminal.
- Result identity, hashes, paths, sizes, authority, and transcript bytes are
  verified natively before History presents completion.

WSS/live server transcription, general media conversion, production
authentication, persistent multi-user service, enterprise DNS/certificates/
firewall/ZPA, promoted diarization, simultaneous full-profile residency,
sustained capacity/SLOs, and the remaining agent product surfaces are later
gates—not hidden current capabilities.

## Repository map

```text
desktop/     Tauri 2 + React desktop app and native/runtime tests
server/      Python 3.12 contract, durable batch service, router, and worker
infra/       Private server-node bootstrap and policy
docs/        Current architecture/status, ADRs, specs, plans, runbooks, evidence
```

Runtime data belongs under Tauri's canonical app-data directory. On Windows
that is `%APPDATA%\com.mcnatg1.yap`. The stock NSIS installer lifecycle is
tested only in a disposable Windows environment.

## Desktop development

Requirements: Node 24, pnpm 11.7.0, Rust 1.96, and PowerShell Core 7.4+ for
repo-owned Windows automation.

```powershell
cd C:\dev\cohere-transcribe-local\desktop
corepack pnpm@11.7.0 install --frozen-lockfile
pnpm test
pnpm build
pnpm tauri dev
```

See [desktop/README.md](desktop/README.md) for focused Playwright, WDIO, and
installer commands. Do not run the installer lifecycle in an everyday Windows
profile.

## Server development

The portable service supports Python `>=3.12,<3.13`.

```powershell
$env:PYTHONPATH = (Resolve-Path "server/src").Path
uv run --isolated --no-project --python 3.12 --with pytest pytest server/tests
```

See [server/README.md](server/README.md) and the
[server-node runbook](docs/runbooks/yap-server-node-setup.md). The GB10 gate is
an exact-head release boundary, not a routine local test.

## Canonical documentation

- [Current status](docs/CURRENT-STATUS.md)
- [Current architecture](docs/architecture/CURRENT-ARCHITECTURE.md)
- [Long-term Voice OS architecture frame](docs/VOICE-OS-ARCHITECTURE.md)
- [Executable ownership map](docs/architecture/boundaries/EXECUTABLE-OWNERSHIP.md)
- [Roadmap](docs/roadmap/ROADMAP.md)
- [ADR index and implementation status](docs/adr/README.md)
- [Public security posture](docs/security/SECURITY-POSTURE.md)
- [Third-party provenance](docs/provenance/THIRD-PARTY.md)
- [Executable ownership review findings](docs/evidence/executable-ownership-review/FINDINGS.md)
- [Documentation index](docs/README.md)
- [Changelog](CHANGELOG.md)

Product and visual intent remain in [PRODUCT.md](PRODUCT.md) and
[DESIGN.md](DESIGN.md). If a historical plan conflicts with current code or a
canonical document, the executable system and accepted ADR/spec win.
