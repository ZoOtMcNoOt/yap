# Cloud development

This workspace supports frontend, browser, native Rust, portable server, and
provider-lifecycle development without a GPU or model weights.

## Set up

The setup script targets the managed Debian 13 x86_64 image with Node 24,
Python 3.12, uv, Corepack, Chromium, a C compiler, and pkg-config already present.
It installs Rust 1.96 with Clippy/rustfmt, pnpm 11.7.0, PowerShell 7.6.0,
GTK/WebKit/audio/tray development libraries, CMake, Xvfb, and Tini. Downloads and
native libraries live in ignored `.tools/`; no administrator access is needed.

```bash
bash verification/setup-cloud-dev.sh
source verification/cloud-env.sh
```

Source the environment file in each new shell. It selects the user-owned native
library prefix, cached Sherpa runtime archive, and repository-local pnpm store. This also keeps license checks on the same package index as installation. Setup preserves locked package
versions, package signatures, the cloud proxy, and TLS verification.

PowerShell uses its published release SHA-256. The Linux Sherpa 1.13.4 archive
is pinned to the observed upstream download SHA-256 in the setup script; it is
a development runtime, separate from the qualified Windows shipping artifact.
No model weights are downloaded. Third-party origins:
[Rust](https://www.rust-lang.org/),
[PowerShell](https://github.com/PowerShell/PowerShell),
[Sherpa](https://github.com/k2-fsa/sherpa-onnx), and Debian packages.

## Build and verify

Run suites sequentially on the four-core workspace. Timing/concurrency fixtures
should not compete with a full native compilation.

```bash
source verification/cloud-env.sh
cd desktop
pnpm test
pnpm build
pnpm test:e2e
pnpm tauri build --debug --no-bundle
cd ..
.tools/native/usr/bin/tini -s -- cargo test --manifest-path desktop/src-tauri/Cargo.toml --locked
cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --all --check
cargo clippy --manifest-path server/orchestrator/Cargo.toml --locked --all-targets --all-features -- -D warnings
.tools/native/usr/bin/tini -s -- cargo test --manifest-path server/orchestrator/Cargo.toml --locked --all-features -- --test-threads=1
bash verification/test-cloud-server.sh
node --test desktop/tests/scripts/release-contract/documentation-truth.contract.mjs desktop/tests/scripts/release-contract/dependency-license.contract.mjs desktop/tests/scripts/release-contract/provenance.contract.mjs
cd server
uv run --locked ruff check . ../infra/yap-server-node/owned-process-supervisor.py
```

Rust feature upgrades can leave several large versions of Yap artifacts in the
32 GiB workspace. Check `df -h /workspace` before a rebuild. Once Cargo has
finished, `cargo clean --manifest-path desktop/src-tauri/Cargo.toml -p yap-desktop`
removes only disposable package build artifacts; source, fixtures and evidence
remain. Use `CARGO_BUILD_JOBS=1` for the following native rebuild to limit
simultaneous linking. A linker failure under disk pressure is not a test result.

Tini reaps orphaned child processes in container lifecycle tests. The server test
wrapper uses a digest-pinned
[Ubuntu development image](https://github.com/catthehacker/docker_images), whose
real `/usr/bin/python3.12` meets the private-launcher contract. Docker must be
running and the image must be downloaded once; test execution then has no
external network. The wrapper mounts the checkout and existing Python/Rust
runtimes and runs under your user ID with Docker's init. It does not mount the
Docker socket or start real model services.

The managed network currently permits the GitHub Container Registry image;
Docker Hub hit an anonymous pull limit, and the MCR image's blob download was
denied. Use the documented image rather than changing network settings.

## Local database tests

The cloud can exercise real knowledge/terminology persistence without models:

```bash
bash verification/setup-cloud-postgres.sh
source .tools/postgres/env
cd server
PYTHONPATH=src .venv/bin/python ../verification/run-governed-knowledge-postgres-suite.py
PYTHONPATH=src .venv/bin/python -m unittest tests.knowledge.test_terminology_policy tests.knowledge.test_terminology_service tests.api.test_terminology_api tests.knowledge.test_terminology_runtime -v
```

The script installs Debian Postgres 17.11 and pgvector 0.8.0 in a separate user-owned
prefix, starts a loopback-only cluster with private data/credentials, and enables
the vector extension. Repeated setup retains the database. Its test DSN stays in
ignored `.tools/postgres/env`; do not commit or print it. Nineteen real database
tests passed with no skips, including permission-safe retrieval, durable reviewed
sources, snapshots and explicit team management. These development versions do
not renew the separate ARM64 production database lock or enterprise qualification.

Personal/shared terminology HTTP tests use an owner-private credential file and the
production configuration builder against this database. Authentication is a
deterministic token fixture; it does not qualify Entra. All 28 focused cases pass
with the database environment loaded. The isolated portable suite intentionally
does not inherit these credentials; its 18 terminology database/HTTP skips are checked here.

Stop the cluster when it is no longer needed:

```bash
source verification/cloud-env.sh
.tools/postgres/native/usr/lib/postgresql/17/bin/pg_ctl -D .tools/postgres/data -m fast -w stop
```

## Enable terminology on a private server

Configure organization authentication using the [server instructions](../../server/README.md), then explicitly set:

```bash
export YAP_TERMINOLOGY_RUNTIME=postgres
export YAP_TERMINOLOGY_DSN_FILE=/run/yap/knowledge.dsn
```

The credential must be an absolute, owner-private regular file (mode 0600 on
Unix), containing the canonical knowledge database DSN. Do not print or commit
it. When Scribe is enabled, configure its terminology resolver against this same
ledger. Connection, statement and lock timeouts are bounded to three seconds.
Startup validates persistence before advertising `personalTerminology`, the existing personal-service capability used to enter terminology settings. Authorized shared scopes are discovered separately.
Missing/invalid credentials produce a redacted configuration error.

This service requires no inference model. The desktop exposes it in Settings →
Personalization after explicit connection/sign-in and successful capability
checks. Scribe remains separately configured; saving a term does not enable
correction or qualify ASR/provider effectiveness. Unset both variables to leave
the service unconfigured, or set the runtime to `disabled` with no credential
variable. Credentials without an explicit enabled mode are rejected.

Shared scopes additionally require `YAP_TERMINOLOGY_POLICY_FILE`, an absolute path
to an owner-private regular JSON file (0600 on Unix), up to 64 KiB. It is loaded
once at startup; apply grant changes with a server restart, then Refresh terms.
The same immutable policy feeds management and Scribe's snapshot resolver. Both
services must use the canonical terminology database. No policy means personal
management only; organization roles in tokens cannot enable shared management.

```json
{
  "tenants": [{
    "tenantId": "your-verified-tenant-id",
    "label": "Your organization",
    "administratorRoles": ["knowledge.terminology.admin"],
    "teams": [{
      "teamId": "clinical",
      "label": "Clinical team",
      "members": ["verified-subject-id"],
      "managers": ["verified-subject-id"]
    }]
  }]
}
```

Use subjects/tenants from the organization identity provider, not display names
or user requests. Managers must be members. The policy accepts at most 32
tenants, 32 teams per tenant, 256 members/managers per team and 32 administrator
roles; duplicates, unknown fields, invalid grants, linked/nonregular files and
excess size fail startup with redacted errors. Labels are readable text up to
128 characters. This explicit policy is the current IT handoff; it does not
claim automatic directory synchronization. Keep policy/credential files outside
source control and apply the organization's actual access policy before deployment.

## Enable knowledge connections on a private server

Configure organization authentication, the canonical knowledge database and the
existing reviewed-generation admission pipeline. Provision its schema with
`install_knowledge_schema` and the content-free audit table with
`install_knowledge_tool_audit_schema`; startup checks both before advertising
`knowledgeConnections`. Its six startup probes cover the active-build pointer, build ledger,
concepts, relationships, proposals and audit tables. Provisioning is an operator
action, not an API side effect.

```bash
export YAP_KNOWLEDGE_CONNECTIONS_RUNTIME=postgres
export YAP_KNOWLEDGE_CONNECTIONS_DSN_FILE=/private/yap/knowledge.dsn
```

The DSN file must be an absolute, owner-private regular file (0600 on Unix),
up to 4096 bytes, containing one valid connection string. Symlinks and FIFOs
are refused. Credentials are loaded once; changing the file requires restart.
Unconfigured or explicit `disabled` mode without credentials exposes no read
capability. Invalid configuration or missing tables fails startup with redacted
errors. A configured database without an active reviewed generation returns 503
until admission and activation complete; it does not become synthetic knowledge.

Connections needs no Librarian/reasoning runtime. After explicit connection and
sign-in, open Knowledge → Connections → Browse topics. The existing permission
projection admits only the token principal's visible topics for `knowledge.read`.
Knowledge → Review proposals also opens an owned saved connection reference
without a model. Reading requires both endpoints to remain visible in the current
generation. **Discard proposal…** retires an owned suggestion after confirmation,
including obsolete proposals, while retaining history and sources. Retry the same
reference if confirmation is lost. This setting grants no new source access or
canonical publication.
See the [contract and limits](../specs/knowledge-connections.md).

Focused development checks use the private local Postgres environment:

```bash
source verification/cloud-env.sh
source .tools/postgres/env
PYTHONPATH=server/src:server server/.venv/bin/python -m unittest \
  tests.knowledge.test_knowledge_connections_runtime \
  tests.knowledge.test_postgres_knowledge_connections \
  tests.api.test_knowledge_connections_api \
  tests.knowledge.test_connection_proposal_discard \
  tests.api.test_connection_proposal_inspection_api
```

These checks create synthetic reviewed generations and vectors only in isolated
test tenants; they do not qualify an inference model or a production corpus.

## Browser development

```bash
source verification/cloud-env.sh
cd desktop
pnpm dev --host 127.0.0.1
```

Open the loopback Vite URL for the browser preview. The existing browser fixtures
simulate native/service responses for workflow tests. Production transport stays
native-owned.

The cloud environment file explicitly selects `/usr/bin/chromium` through
`YAP_PLAYWRIGHT_EXECUTABLE_PATH`. Playwright's pinned-browser download domain is
blocked here. `YAP_PLAYWRIGHT_VIDEO=off` avoids downloading its video encoder;
failure screenshots and traces remain enabled. Outside this workspace, leave
these variables unset to use Playwright's default browser and video behavior.
Browser warmup and test workers use the same browser selection.

## Verification boundary

A Linux native build verifies compilation and the portable Rust behavior.
Windows text injection, local-model load guards, native shortcut enrollment,
WAM identity, tray/island hit regions, and NSIS installation still need Windows.
Linux compilation does not make those Windows product paths supported on Linux.

Real inference accuracy, performance, GPU residency/capacity, and enterprise
connectivity require their target environments. The
[project hill-climbing goal](../plans/active/2026-10-02-yap-project-hill-climb.md)
keeps those handoffs separate from ordinary development. Fresh check results
and unresolved limitations belong in [current status](../CURRENT-STATUS.md).
