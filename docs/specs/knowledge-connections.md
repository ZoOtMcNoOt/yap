# Knowledge connections

**Owner:** Grant McNatt. **Contract:** [OpenAPI](../../server/openapi/openapi.json).

Connections reads the current reviewed Postgres knowledge generation without invoking a model. It uses the existing OKF compiler, source admission, active-generation ledger and permission view. Activation still requires the existing complete projection; the explorer does not invent a corpus, vectors or approval.

| Request | Result |
| --- | --- |
| `GET /v1/knowledge/concepts?search=…` | Up to 12 authorized topics, stable concept-ID order, literal case-insensitive title search. The required search may be empty, otherwise it has at most 128 trimmed characters. |
| `GET /v1/knowledge/connections?conceptId=…&generationSha256=…` | The authorized topic and up to 16 incoming/outgoing canonical edges, at most 17 nodes. The generation must match the preceding topic view. |
| `GET /v1/knowledge/connection-proposal?proposalId=…` | One owned, proposed typed Curator connection with two exact source excerpts. The required reference is 64 lowercase hexadecimal characters. |

All endpoints authenticate organization identity and fix purpose to `knowledge.read`. Callers cannot select a tenant, subject, agent grant, limit or purpose. Both edge endpoints must be visible before selection, limits and `hasMore`. Hidden and unknown topics share a 404; a changed generation returns 409 and requires fresh topic discovery. Empty authorized discovery returns an empty page; missing reviewed storage returns 503. Disabled service routes return 501. Other methods return 405.

Every edge carries its type, authority (`asserted`, `human_confirmed`, `derived`) and exact source path, revision and SHA-256. Paired character offsets (within the existing one-million-byte source ceiling) identify source-text links; paired nulls identify declared metadata without inventing a quote. `agent_proposed` relationships are excluded. Responses are limited to 64 KiB, with no partial result on invalid or excessive metadata. Success and failed admitted reads write content-free tool audits; application request logs omit query strings, source text and tokens. Private reverse proxies must likewise omit query strings when logging these routes.

The native bridge owns origin, bearer credentials and the main-window boundary.
Every read, including initial browsing, requires `authorityRevision` from the
shared native `ServerConnectionSnapshot`. Its generation owner changes on
identity/configuration changes; ordinary health checks retain the revision.
Native dispatch compares it to the captured lease, and commit requires that lease
to remain current. No separate authority probe or unbound discovery is used.
Parsing rejects unknown fields, inconsistent generations, duplicate/unrelated
nodes or edges, mismatched source proof and excess bounds.

The four existing Knowledge submission commands require that same revision before
dispatch. Their views clear private drafts/results/retry references when owners
change. An unchanged owner can draft offline, with submissions disabled until
its capability is available. Pending submission/cancellation keeps the form
locked until its promise releases. See the [ownership evidence](../evidence/connection-owned-knowledge/2026-10-03-verification.md).

The UI provides topic discovery, bounded graph/list views, keyboard source inspection, copied citations, neighbor exploration and an eight-topic back path. It retains the existing four Knowledge tasks and their drafts. Changed/denied views clear old results; temporary failures can retry. Native cancellation drops the HTTP read and prevents its result from returning to the UI. It does not undo server SQL that has already started; SQL is read-only, with a five-second per-statement timeout and one-second lock timeout. The desktop request has a 20-second deadline and one concurrent read; the service permits two concurrent reads.

## Agent proposals

Governed traversal and MCP responses retain `relationship_authority`; text evidence
cannot acquire an edge authority. Agents submit connection candidates through
the existing `propose_knowledge` tool with `proposal_type: relationship`.
`proposed_content` is a JSON object with exactly these fields:

| Field | Bound |
| --- | --- |
| `schema_version` | Integer `1` |
| `source_concept_id`, `target_concept_id` | Distinct, trimmed topic IDs, at most 512 characters each |
| `relationship_type` | At most 128 ASCII nonwhitespace characters |
| `rationale` | Trimmed explanation, at most 2,000 characters |

The JSON is limited to 16,384 characters both before parsing and after canonical
escaping. Duplicate keys, extra fields and authority/canonical claims are
rejected. Exactly one citation per endpoint and `expected_generation_sha256`
are required. Storage verifies both endpoints are currently visible and that
their revisions, hashes and character spans match the active generation.
Canonical JSON and citation ordering give equivalent submissions one replay
identity. Existing stored proposal data is retained; new unstructured
relationship submissions are refused. Summary submissions retain their contract.

Candidates remain in the existing noncanonical, owner-scoped journal. Cancellation
and failed success audits roll back publication; discard is owner-scoped and
idempotent, and replay cannot resurrect a discarded candidate. This does not
implement canonical publication or expose a desktop approval action. Coordinator
summary review retains its scope.

Curator's `reviewed-connection` trigger accepts the same candidate JSON in
`reviewedContent` and exactly two `sourceCitations`. It reviews the frozen
identified source pair, returns only a propose/reject decision and rereads
current evidence before atomic journal/audit publication. Each excerpt is at
most 1,024 characters. The desktop selects indexes from a completed owned
Librarian query; native code supplies its generation and source proof and binds
both current connection leases. The responsive form exposes direction,
type/rationale, cited excerpts, cancellation/retry and a proposal reference.
See the [Curator development record](../evidence/curator-connections/2026-10-03/verification.md);
new connection reasoning requires separate model qualification.
Human connection review, publication and rebuilding remain open in the
[project goal](../plans/active/2026-10-02-yap-project-hill-climb.md).
See [configuration](../runbooks/cloud-development.md#enable-knowledge-connections-on-a-private-server)
and [verification/screens](../evidence/knowledge-connections/2026-10-03/verification.md).

## Saved connection inspection

Review proposals accepts a pasted reference or an explicit handoff from Curator's
newly created connection. The service checks the stored candidate, normalized
citations, proposal identity and inherited-policy hash, then reauthorizes both
endpoints against the current reviewed generation. Each returned source identifies
its current title, path, revision, content hash and exact cited range, with at most
1,024 Unicode characters of text. Hidden, unknown, discarded, wrong-type and
foreign-owner references share 404; owned stale generations return 409. Invalid
stored evidence or excess response size fails without returning partial text.
No model runs, canonical relationships change, or human approval is inferred.

HTTP/native candidate fields use `schemaVersion`, `sourceConceptId`,
`targetConceptId`, `relationshipType` and `rationale`; the persisted/tool candidate
JSON above retains its existing snake_case schema.

The native reader validates the reference, typed candidate, proposed status,
exactly two distinct matching endpoints and quote lengths before committing under
the current connection lease. Inspection shares the existing read deadline,
cancellation and admission limits. UI task changes preserve owned drafts; account
changes clear them and hide private evidence immediately. New handoffs cancel an
older read and wait for its completion. Same-owner offline drafts remain editable,
with remote reading disabled. See [inspection evidence](../evidence/connection-proposal-inspection/2026-10-03/verification.md).
