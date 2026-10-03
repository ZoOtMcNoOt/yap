# Connection-owned Knowledge views

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** Five software outcomes verified in the development working tree.

Search, cited answers, proposal bundles and conflict reports could keep private drafts and results when a different account/server became ready. The four request owners now bind to the native connection revision. Offline drafting remains available for the same owner; changing owners clears drafts, results and retry references before adopting the new connection. The [project goal](../../plans/active/2026-10-02-yap-project-hill-climb.md) stays active, including Curator connection review, canonical publication and rebuilding.

## Behavior and ownership

| Outcome | Verified behavior |
| --- | --- |
| Shared native revision | `ServerConnectionSnapshot.authorityRevision` is the existing native generation as a required decimal string. Identity/configuration changes replace it; ordinary health checks retain it. Serialization preserves values above JavaScript's integer range. No identity or credential is exposed. |
| Private drafts/results | The four Knowledge hooks hide prior-owner values immediately, cancel owned work and clear drafts, evidence, errors and retry references. Selected Student/Curator source views unmount when their source evidence disappears. Late submission/poll/cancellation responses cannot restore old results. |
| Offline work and pending controls | Same-owner task switches and health checks retain drafts. Losing availability removes results and blocks submissions while allowing offline drafting. Submission and manual cancellation stay pending until their promises release; they cannot admit another request early. |
| Native dispatch binding | Each of the four start commands requires the snapshot revision and compares it to its captured native lease before reserving/submitting work. Stale, missing or differently formatted revisions cannot retarget private input. Existing origin, token/principal and current-lease commit guards remain. |
| Connections simplification | Every read, including initial browsing, requires that same snapshot revision. The separate authority command/probe and unbound discovery path are removed. Same-owner health checks preserve exploration without an extra read. Browse clicks suppress the default action when a fast response changes the button into a submit control. |

The shared [authority hook](../../../desktop/src/hooks/use-connection-authority.ts) separates draft ownership from result availability. [Native snapshots](../../../desktop/src-tauri/src/server_connector/state.rs) and [connection leases](../../../desktop/src-tauri/src/server_connector/core.rs) remain authoritative. Browser state does not acquire credentials, choose another server or become a durable job owner. Stored proposals, canonical knowledge, original transcripts and accepted corrections are preserved.

## Checks

| Check | Result |
| --- | --- |
| Frontend unit suite | 388 passed; two existing Windows-only skips. |
| Native suite | 1,330 unit and 27 integration passed; 11 existing hardware/model ignores. Three added ownership cases cover snapshot generation/precision, configuration/identity changes and stale dispatch across the four roles. |
| Full Chromium suite | 143 passed; one existing Windows-only island exclusion (144 total). Includes 38 Connections/Knowledge/workspace recovery cases. |
| Production frontend and Linux native application | TypeScript/Vite and Tauri debug/no-bundle passed; 18 existing Linux platform warnings. |
| Documentation, dependency-license and third-party provenance | Eight contract checks passed; rustfmt and diff whitespace passed. |

Before the change, four account-change cases and four delayed-cancellation cases reproduced the failures. The broad renewal also caught an offline-drafting regression, which was corrected and checked across all four tasks. Browser outputs are fixed native-boundary fixtures; the tests qualify interaction, not native IPC or model reasoning. Real storage/HTTP and existing authenticated transport checks retain the [Connections receipts](../knowledge-connections/2026-10-03/verification.md). The server was unchanged in this increment; its 1,715-case isolated suite and 82-case real-Postgres regression retain their preceding receipts.

Commands, after `source verification/cloud-env.sh`: `pnpm --dir desktop build`; `pnpm --dir desktop test`; `.tools/native/usr/bin/tini -s -- cargo test --manifest-path desktop/src-tauri/Cargo.toml --locked`; `pnpm --dir desktop test:e2e`; `pnpm --dir desktop tauri build --debug --no-bundle`; `cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --all --check`; the documentation/license/provenance contract command in the cloud runbook.

No Windows, enterprise identity/networking, real inference, production corpus, compositor or capacity qualification is claimed. Human connection publication and rebuilding remain open in the single project queue.
