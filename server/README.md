# Yap server

The private service behind Yap's recording queue, transcript corrections and
source-cited knowledge workflows. Processing stays on organization-owned
infrastructure; identity, sources and results belong to their authenticated owner.

This guide starts with a model-free development service, then points to the
configuration needed for each capability. [Current status](../docs/CURRENT-STATUS.md)
records what has been verified. The [project goal](../docs/plans/active/2026-10-02-yap-project-hill-climb.md)
orders the remaining work.

## Start a local health service

Use **Python 3.12** and **uv**. From the repository root:

```bash
cd server
uv sync --locked --all-extras
PYTHONPATH=src uv run --locked --all-extras python -m yap_server
```

In another terminal:

```bash
curl http://127.0.0.1:18765/v1/health
```

With no optional runtime configured, this starts a health-only service. Processing
capabilities are unavailable and job routes return `501 NOT_IMPLEMENTED`. No
model, GPU, database or organization credentials are needed for this first step.
Stop the foreground process with Ctrl+C.

On PowerShell, set `$env:PYTHONPATH = 'src'` before running
`uv run --locked --all-extras python -m yap_server`; use `Invoke-RestMethod` for the health URL.
The [cloud guide](../docs/runbooks/cloud-development.md) provides the complete
managed Debian environment and hardware-free checks.

## Choose the capability you need

Features are enabled explicitly, after their runtime dependencies validate.
Having an API contract does not make the corresponding service available.

| Capability | What it provides | Setup or contract |
| --- | --- | --- |
| Batch transcription | Durable jobs, resumable PCM upload, cancellation and immutable results | [Batch development profile](../docs/runbooks/yap-server-node-setup.md#loopback-batch-development-profile) |
| ASR catalog | Verified model, language and route availability at `/v1/asr/capabilities` | [OpenAPI](openapi/README.md) and [capability lock](asr-capabilities.lock.json) |
| Organization identity | Validated access tokens, owner isolation, purpose grants and revocation | [Identity setup](../docs/runbooks/yap-server-node-setup.md#phase-7-application-authentication-mode) and [IT handoff](../docs/runbooks/entra-identity-conformance-handoff.md) |
| Private live admission | Authenticated WebSocket admission on a separate loopback listener | [Live event contract](openapi/live-events.schema.json); live ASR and production HTTPS/WSS remain open |
| Terminology | Personal and explicitly configured team/organization preferred spellings | [Terminology setup](../docs/runbooks/cloud-development.md#enable-terminology-on-a-private-server) and [API](../docs/specs/terminology-api.md) |
| Knowledge connections | Permission-filtered topics, cited relationships, owned proposal discovery and inspection | [Connections setup](../docs/runbooks/cloud-development.md) and [contract](../docs/specs/knowledge-connections.md) |
| Reviewed knowledge | Compile reviewed sources, stage Postgres/pgvector generations and retrieve authorized evidence | [Architecture](../docs/architecture/CURRENT-ARCHITECTURE.md) and [knowledge evidence](../docs/evidence/README.md) |
| Reviewed agent workflows | Corrections, cited answers, proposals and review reports | Runtime configuration below; [provider supervision](../docs/runbooks/provider-supervisor-service.md) and [admission](../docs/runbooks/agent-admission-service.md) |

The committed ASR catalog advertises the qualified Cohere `en-US` fixed-batch
route. Nemotron, Tiron, additional locales and timing promises require their own
promotion evidence. Candidate launchers and focused tests do not expand the
catalog or qualify production capacity.

## Configure a private runtime

### Bind and authenticate

REST defaults to `127.0.0.1:18765`. `YAP_SERVER_HOST` must be a **numeric loopback
address**; `YAP_SERVER_PORT` selects its port. Use an explicit SSH local forward
for development or an approved secure edge for external access. The service does
not open a firewall or create a production HTTPS/WSS endpoint.

Organization operation uses `YAP_AUTH_MODE=entra` with IT-approved tenant,
audience, allowed client IDs, scope, role policy and private identity storage.
Follow the [identity setup](../docs/runbooks/yap-server-node-setup.md#phase-7-application-authentication-mode)
for the exact variables. Owner and tenant identities come from validated tokens,
never request fields. Test issuers cannot enter production configuration.

The isolated `development_loopback` authentication mode requires
`YAP_SERVER_CONFIGURATION=development`; it cannot be enabled in release
configuration. It is not an organization identity substitute.

The authenticated live listener defaults to loopback port `18766`, selected by
`YAP_SERVER_LIVE_PORT`. REST `/v1/live` is not an upgrade endpoint. Clients need an
explicit live origin; REST health is not live discovery.

### Batch recordings

Use the [two foreground launchers in the node runbook](../docs/runbooks/yap-server-node-setup.md#loopback-batch-development-profile)
instead of reconstructing provider environments. Batch mode requires Linux,
`YAP_BATCH_ASR_ENABLED=1`, a full checked Git SHA, mode-0700 private job storage,
verified model files, the immutable model lock and the checked provider runtime.
The vLLM route additionally requires its separately running checked launcher,
numeric-loopback endpoint and private API key.

The launchers use the locked Python environment without network resolution.
Set `YAP_UV_BINARY` to an absolute executable if needed, and prepare its cache
before starting. Each provider owns its internal Docker network, loopback proxy,
private `YAP_PROXY_PROCESS_GROUP_FILE` and verified teardown. No model port is
Docker-published. Optional language preflight needs its separately verified model,
image and preparation receipt; absent inputs leave the capability unavailable.

Upload chunks are raw `pcm_s16le` bytes with `application/octet-stream` content
type. A replay with the same logical key and SHA-256 succeeds; different bytes
under that key return `409 CONTENT_IDENTITY_CONFLICT`. Manifest binding and
immutable result identities are defined in [OpenAPI](openapi/README.md).

The development profile bounds HTTP work, queue depth, retained records and
chunks. Its four-hour mono PCM16/16 kHz admission ceiling is a resource boundary;
it does not establish representative transcription quality at that duration.
Detailed limits and provider qualification commands remain in the
[node runbook](../docs/runbooks/yap-server-node-setup.md) and the preserved
[batch-runtime reference](../docs/archive/implementation-evidence/2026-10-03-server-implementation-history.md#loopback-batch-asr-path).

### Knowledge and reviewed agents

Terminology and connection reads need organization authentication and explicitly
configured private Postgres credential files. Use their setup guides above.
Postgres/pgvector is the current knowledge projection. Generation provisioning,
reviewed source admission and activation are
[explicit operator/reviewer actions](../docs/specs/knowledge-publication.md);
starting a read service does not create or publish knowledge.

The eight roles share bounded admission and source authorization. This table
names each runtime switch and its configuration owner:

| Role | Runtime switch | Outcome and configuration |
| --- | --- | --- |
| Scribe | `YAP_TRANSCRIPT_CORRECTION_RUNTIME=warm_qwen` | Propose transcript corrections; [configuration](src/yap_server/agents/transcript_correction_runtime.py) |
| Archivist | `YAP_ARCHIVIST_RUNTIME=reviewed_capture_postgres` | Stage an owned completed recording for review; [configuration](src/yap_server/agents/archivist_runtime.py) |
| Librarian | `YAP_LIBRARIAN_RUNTIME=permission_safe_postgres` | Retrieve authorized source excerpts; [configuration](src/yap_server/agents/librarian_runtime.py) |
| Analyst | `YAP_ANALYST_RUNTIME=warm_gemma` | Answer from cited evidence; [configuration](src/yap_server/agents/analyst_runtime.py) |
| Student | `YAP_STUDENT_RUNTIME=warm_qwen` | Ask a learning question grounded in an exact excerpt; [configuration](src/yap_server/agents/student_runtime.py) |
| Curator | `YAP_CURATOR_RUNTIME=warm_gemma` | Save a source-bound proposal for review; [configuration](src/yap_server/agents/curator_runtime.py) |
| Coordinator | `YAP_COORDINATOR_RUNTIME=warm_gemma` | Assemble a noncanonical proposal bundle; [configuration](src/yap_server/agents/coordinator_runtime.py) |
| Auditor | `YAP_AUDITOR_RUNTIME=warm_gemma` | Report source-cited findings without mutation; [configuration](src/yap_server/agents/auditor_runtime.py) |

Each role needs its own absolute admission-socket and private knowledge-DSN-file
paths. Model-backed roles also require their immutable profile and candidate-lock
paths. The linked builders list the exact variable names and validation. Missing
or conflicting inputs stop configuration; supplying paths while a runtime is
unset or disabled is rejected.

Model-backed requests use already-warm providers. Requests never start, swap or
fall back to another model. The [admission broker](../docs/runbooks/agent-admission-service.md)
owns fair scheduling, route capacity, queue-inclusive deadlines and cancellation
acknowledgement. Installation does not start services; broker recovery requires
containing prior external workers before restarting lost lease state.

Staging, answers, proposed corrections, proposals, bundles and reports do not
activate knowledge. Accepting a transcript correction creates a separate native
revision and preserves raw ASR. Canonical knowledge publication requires its
explicit authorized human review and complete projection checks.

## Run development checks

From `server/`, with the locked environment installed:

```bash
uv run --locked --all-extras ruff check .
PYTHONPATH=src uv run --locked --all-extras python -m unittest tests.contract.test_contract -v
```

On PowerShell, set `$env:PYTHONPATH = 'src'` before the Python command.
For the complete portable suite in the managed cloud, run this from the
repository root:

```bash
source verification/cloud-env.sh
python verification/audit-server-dependencies.py
bash verification/test-cloud-server.sh
```

The wrapper runs the locked suite in an isolated, digest-pinned Ubuntu container
without external networking or real model services. The
[cloud guide](../docs/runbooks/cloud-development.md) explains Docker setup,
real local Postgres tests and Rust orchestration checks. Run heavyweight suites
sequentially. [Test documentation](tests/README.md) describes the test layers.
The core dependency audit uses an isolated pinned tool and refuses advisories or
unavailable package evidence. Model overlays and container images retain their
separate [audit scope](../docs/runbooks/dependency-audit-policy.md).

## Qualify models and deployment

Private-node gates need reviewed clean heads, exact runtime/model identities,
licensed private inputs and new evidence destinations. They are separate from
portable tests. Start with the [node runbook](../docs/runbooks/yap-server-node-setup.md)
for ASR preparation and gates, the [provider runbook](../docs/runbooks/provider-supervisor-service.md)
for lifecycle checks, and [identity conformance](../docs/runbooks/entra-identity-conformance-handoff.md)
for enterprise inputs.

Private credentials, model outputs, audio, database content and raw measurements
stay outside Git and public logs. Public evidence records only approved hashes,
counts and bounded outcomes. Historical passing gates certify their recorded
heads and environments; they do not qualify current changes, simultaneous model
residency, sustained capacity or production deployment.

The complete prior server README, including all phase narratives, qualification
receipts, rejected candidates and detailed evaluation commands, is preserved in
the [server implementation history](../docs/archive/implementation-evidence/2026-10-03-server-implementation-history.md).
Current verification belongs in [status](../docs/CURRENT-STATUS.md) and the
[evidence index](../docs/evidence/README.md).

## Repository map

| Path | Responsibility |
| --- | --- |
| [`openapi/`](openapi/README.md) | HTTP contracts and live event schemas |
| `src/yap_server/` | API, identity, durable jobs, knowledge and bounded agent services |
| `orchestrator/` | Rust provider supervision and admission |
| `runtime/` | Pinned model-runtime images, build inputs and notices |
| `tests/` | Portable, database and private-gate checks |
| [`../infra/yap-server-node/`](../infra/yap-server-node/) | Host setup and foreground launchers |

Runtime models live on the private node, outside Git. The server and shared
contracts remain in this repository; the [roadmap](../docs/roadmap/ROADMAP.md)
and [ADR 0018](../docs/adr/0018-three-repo-topology.md) retain the future repository
boundaries.
