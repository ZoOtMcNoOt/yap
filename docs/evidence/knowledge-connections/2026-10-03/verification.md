# Knowledge connections: stored-read path

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** 6/7 software outcomes verified; connection orchestration, human publication and rebuilding remain open.

The desktop previously exposed agent searches and proposal reports, but no way to explore stored topic relationships. Connections now reads the canonical Postgres projection through authenticated server/native owners, independently of inference. It offers topic discovery, a bounded graph, a complete list of returned relationships, source proof and neighbor navigation. The entire [project goal](../../../plans/active/2026-10-02-yap-project-hill-climb.md) remains active.

## Earlier work and remaining agent boundary

| Existing owner | Executable behavior and boundary |
| --- | --- |
| [OKF compiler](../../../../server/src/yap_server/knowledge/okf_compiler.py) | Deterministically compiles source-text links and declared typed relationships. Authority is explicit; agent-proposed edges are noncanonical. |
| [Generation ledger](../../../../server/src/yap_server/knowledge/generation_ledger.py) and [source admission](../../../../server/src/yap_server/knowledge/knowledge_source_admission.py) | Stage reviewed source, permissions and projections, then activate a complete generation. The explorer does not bypass these gates. |
| [Permission-filtered relationship retrieval](../../../../server/src/yap_server/knowledge/postgres_relationship_retrieval.py) | Existing outgoing recursive traversal remains for agents. New incoming/outgoing one-topic reads and title browsing retain the same principal/purpose/generation authority. |
| [Governed proposal owner](../../../../server/src/yap_server/knowledge/governed_knowledge_proposals.py) and [proposal ledger](../../../../server/src/yap_server/knowledge/knowledge_proposals.py) | Persist cited, owner-scoped noncanonical summaries or typed connection candidates. Both connection endpoints require current exact evidence. Discarding a proposal does not mutate canonical knowledge. This is not a complete connection approval UI. |
| [Curator publisher](../../../../server/src/yap_server/agents/curator_publisher.py) / existing eight-role workflows | Publish cited summary proposals and audit terminal results, without making them canonical. Coordinator review bundles remain summaries. Connection workflow orchestration, human publication and rebuild recovery still need completion. |

The generic agent response now retains `relationship_authority` through governed traversal and MCP serialization. Relationship evidence requires one canonical authority; text evidence cannot acquire one. The existing character budget counts the authority value and returns or excludes the complete item. Three portable contract cases, two real-Postgres cases covering all three authorities and owner isolation, and one MCP transport case pass. No ninth agent, Neo4j service or force-layout dependency was added.

The typed-candidate increment completes four proposal-boundary outcomes within the still-open
agent/publication journey: strict bounded edge intent, exact evidence at both
endpoints, stable owner-scoped replay/discard, and verified storage/MCP behavior.
Six portable contract and eight actual Postgres/MCP cases pass. The candidate
stores two topic IDs, type and rationale as canonical JSON in the existing journal;
it cannot claim human authority or change the graph. Actual model reasoning,
desktop human review, canonical publication and rebuilding are not qualified by
these tests. Existing unstructured stored proposals remain data.

## Screen review

All accepted captures use fresh Chromium rendering of fixed native-boundary records, no customer corpus or model. They qualify interaction/layout only; actual stored relationships and identity boundaries are checked separately.

1. [Topic discovery](01-topics.png): readable titles and types; initial browsing is explicit and search is bounded.
2. [Graph and source details](02-graph-source.png), [diagram detail](05-graph-detail.png): fixed neighboring topics, directed links, source authority and an explicit next-topic action. No continuous graph simulation.
3. [Narrow list and source](03-list-narrow.png): all returned relationships remain readable and the inspected source appears below the list.
4. [360px source details](04-source-mobile.png): wrapping actions, complete source identity and no horizontal page scrolling. This is a browser stress case; native minimum window size and Windows qualification remain separate.

The first review found excessive heading/navigation height on small windows. Connections now omits repeated panel headings and the task strip scrolls horizontally. Existing search/question/proposal/conflict drafts stay mounted. Graph nodes have fixed height and bounded labels; source details preserve full titles. Inspiration remains documented in the [shared design review](../../design-refresh/2026-10-03/review.md), including Mobbin screens, linked-note flow and sections, and the explicit latest-Wispr/Apple research gap.

## Defined acceptance outcomes

| Outcome from the project queue | State |
| --- | --- |
| Inventory earlier compiler, relationship and agent work | Verified inventory above; proposal publication is distinguished from canonical knowledge. |
| Bounded current-generation authorized neighborhood with source authority | Eight real-Postgres cases pass, including incoming/outgoing edges, exact source proof, hidden endpoints/counts, isolated topics and revocation. |
| Authenticated service and connection-owned native reads | Strict queries, required generation, private startup, current native lease and source-bound parsing; targeted HTTP/config/native checks pass. |
| Responsive list/graph, keyboard inspection and source details | Ten browser cases pass at 360/720/1440px with keyboard inspection and back navigation. |
| Cancellation, retry, empty/unavailable views and local independence | Browser recovery checks and actual native in-flight HTTP cancellation pass; stale/changed views clear private results. |
| Connection-building agents, human review, publication and rebuilding | **Open.** Typed candidate admission is checked at storage/MCP, but Curator orchestration and the human publication/rebuild journey are incomplete. Reviewed-source admission remains the canonical gate. |
| Real storage, API/native/browser checks and separate inference qualification | Read-path broad checks pass below. No model/corpus/Windows promotion is claimed. |

## Checks

| Check | Result |
| --- | --- |
| Local Postgres storage (8), authenticated HTTP (8), portable runtime configuration (4) | 20 passed, no skips; private Postgres 17.11/pgvector 0.8.0. Synthetic 768-dimensional vectors only satisfy existing fixture activation. |
| Agent authority, MCP, Librarian and governed/storage/API regression | 65 passed, no skips; actual compiled source authority reaches the model-facing response. |
| Typed connection candidate contract/storage/MCP | 14 passed, no skips; source-bound rejection, replay, revocation, cancellation and failed-audit rollback leave canonical edges unchanged. Expanded regression includes the three existing real-Postgres Curator cases. |
| Expanded final agent/Curator/storage/API regression | 82 passed, no skips. |
| OpenAPI runtime/path/examples contracts | 18 passed. |
| Native focused parsing, transport, authority lease and cancellation | 7 passed; full native 1,327 unit + 27 integration passed, 11 existing model/hardware ignores. |
| Browser Connections and shared design/preference subset | 16 passed initially; final Connections subset 10 passed, including delayed authority confirmation and preserved same-connection exploration. |
| Full isolated server suite after typed candidate integration | 1,635 passed, 80 declared skips (1,715 total). Sixteen connections, two agent-authority and eight candidate database cases pass against real local Postgres; the other 54 remain declared isolation boundaries. |
| Frontend unit and production/Linux native build | 388 passed, 2 existing declared skips; TypeScript/Vite and Linux Tauri debug/no-bundle passed, with 18 existing platform warnings. |
| License/provenance/documentation contracts | 8 passed; final documentation-state check recorded below. |
| Full browser renewal | 126 passed, 1 declared Windows-only skip (127 total). |

Successful and failed admitted reads write content-free audits. Private search/source strings and tokens do not enter application structured logs or returned error text. Tests exercise literal wildcard search, duplicate/caller-authority queries, concurrency limits, excessive Unicode response size and unavailable topics. Private DSN reading now refuses FIFOs without waiting for a writer; regular-file ownership/size constraints remain.

See the [contract](../../../specs/knowledge-connections.md) and [private runtime configuration](../../../runbooks/cloud-development.md#enable-knowledge-connections-on-a-private-server). Native cancellation drops the request future; it does not undo read-only SQL already running. End-to-end real Entra/WAM, a production corpus/model, private networking and Windows focus/compositor behavior remain unqualified.

The final authority guard caught a readiness regression in the ref/state handoff. Authority confirmation now uses one React state owner, and all ten Connections cases pass without loosening the access checks. A delayed same-connection recheck hides results until confirmation, then restores the existing graph and search; a changed connection clears both.

The agent integration renewed the frozen governed portable suite at 176 cases.
Full verification exposed a timing-dependent NeMo worker test: response delivery
can precede socket cleanup, so a following request may use another pooled worker.
The test now sends three times the pool capacity and verifies bounded reuse and
request completion. No serving or inference behavior changed.

The expanded real-Postgres check also renewed the existing Curator capacity test.
Its cross-owner discard assertion expected `PermissionError`; the executable
owner-filtered journal returns the same `LookupError` as absence. The assertion
now checks that existing concealment contract; no production disposition changed.

The frozen summary qualification fixture still rejects relationship substitutions.
It now fails those at typed argument validation; a separate summary-content
mutation continues to verify the exact frozen evidence gate. No fixture or
qualification input was widened to credit connection reasoning.

Typed-candidate focused command, with the private database environment loaded:
`PYTHONPATH=server/src:server server/.venv/bin/python -m unittest tests.knowledge.test_connection_proposal_contract tests.knowledge.test_postgres_connection_proposals -v`.

Commands: `verification/test-cloud-server.sh`; `pnpm --dir desktop test`;
`pnpm --dir desktop test:e2e`; `cargo test --manifest-path desktop/src-tauri/Cargo.toml`;
`pnpm --dir desktop tauri build --debug --no-bundle`; the focused Postgres command
in the runbook; Ruff and the documentation/dependency-license/provenance contracts.
The final focused HTTP/contract run also verifies actual returned pages and
neighborhoods against OpenAPI, including malformed UTF-8 refusal and the existing
permission-safe retrieval route (31 passed). Current snapshots were inspected after
the readiness correction. `git diff --check` passes.


## Connection ownership renewal

The [five-outcome ownership increment](../../connection-owned-knowledge/2026-10-03-verification.md)
replaces the earlier authority probe/discovery path with a required shared native
snapshot revision. Graph browsing/navigation and the four Knowledge submissions
bind that revision before dispatch. Same-owner health checks retain work without
an extra graph read; offline drafts remain usable. Different accounts/servers
clear private state, including late responses and nested source reviews.

The renewed checks pass 1,330 native unit plus 27 integration, 388 frontend and
143 browser cases (144 total with the existing Windows island exclusion). Eleven
Connections and 25 Knowledge journey cases pass alongside both workspace recovery
cases. TypeScript/Vite, Linux Tauri debug/no-bundle and eight documentation/license/
provenance contracts pass. Earlier receipts above describe their earlier boundaries;
human connection publication and rebuilding remain open.
