# Terminology API

**Owner:** Grant McNatt. **Contract:** [OpenAPI](../../server/openapi/openapi.json). **Authority:** [ADR 0028](../adr/0028-model-independent-terminology-authority.md).

Vocabulary management requires organization authentication and explicit private Postgres configuration, independently of models. Personal ownership comes from token tenant/subject. Shared visibility, team managers, labels and organization administrator roles come from one operator-owned policy. A request selects a discovered scope; it cannot create a membership or grant.

| Method and route | Behavior |
| --- | --- |
| `GET /v1/terminology/scopes` | Return at most 34 authorized scopes: Personal, configured organization, and visible teams. Each includes `scopeId`, `kind`, trusted `label` and `canManage`. No query parameters. Without shared policy, return Personal only. |
| `GET /v1/terminology?scopeId=…&locale=en-US&after=…` | Return up to ten latest nondeleted records in that exact tenant/scope for the explicit locale plus `und`. The optional record-ID cursor grants no authority. |
| `GET /v1/terminology/{recordId}?scopeId=…` | Return the current record in the authorized scope. Unknown, deleted and other-scope records return 404. |
| `POST /v1/terminology?scopeId=…` | Accept exactly `mutationId`, `locale`, `canonicalForm`, `variants`, `sensitivity`. Bind creation identity to principal and scope. Identical replay returns the original receipt; changed content returns 409. Recheck management before replay. |
| `PUT /v1/terminology/{recordId}?scopeId=…` | Accept exactly `expectedVersion`, `canonicalForm`, `variants`, `sensitivity`; append the next version. Owner, scope and locale are immutable. |
| `DELETE /v1/terminology/{recordId}?scopeId=…` | Accept exactly `expectedVersion`; append a tombstone. Preserve history and refuse restoration of that lineage. |

Viewing a team or organization does not grant editing. Unavailable scopes return 404; visible read-only mutations return 403. Malformed/extra fields return a redacted 400, stale versions 409, and unavailable persistence a retryable 503. Responses include `scopeId`; native transport checks scope, record/content/version/locale and bounded pages. Forms and variants remain body fields, outside URLs and logs.

Forms contain 1–512 characters, without surrounding whitespace, newline or NUL. Variants contain 1–64 casefold-distinct forms. Sensitivity uses the existing domain enum. Locale is a valid domain BCP-47 tag or `und`; it does not establish model support. Versions are positive integers, excluding booleans.

Personal IDs and stored records retain their existing identity scheme. Shared IDs additionally bind scope/owner. Ledger writes serialize per tenant/record and append history. Jobs and correction requests freeze terminology using the same trusted policy; changes and tombstones do not rewrite admitted snapshots or original transcripts.

Native transport owns credentials, route/session leases and the connection revision. Discovery returns that revision to the renderer; subsequent native requests must match it before dispatch, and responses require the lease to remain current. It is not an HTTP parameter or credential. Drafts stay in their chosen scope, survive temporary failure and require deliberate conflict comparison. A different native revision clears the old draft on discovery and refuses earlier submission. Sign-out clears private loaded data. Refresh discovers updated viewing/editing grants; a revoked scope requires cancellation and explicit selection of another scope.

See [configuration](../runbooks/cloud-development.md#enable-terminology-on-a-private-server). Saving terminology does not enable inference or qualify a provider's use of these terms. Actual directory integration, Windows/WAM and model effectiveness require separate evidence.
