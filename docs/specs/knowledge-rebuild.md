# Desktop reviewed-source rebuild contract

**Owner:** Grant McNatt. **Status:** Proposed; 0/7 implemented outcomes in the
[single active queue](../plans/active/2026-10-02-yap-project-hill-climb.md#current-increment-complete-the-authenticated-desktop-rebuild-workflow).
This contract records the audited interface before implementation. The
[operator service](knowledge-publication.md) exists; a desktop rebuild caller
does not yet exist. Preserve the proposal/Git-review workflow and all other
roadmap work. These controls cannot certify Git or deployment approval.

## Product workflow

Add a Rebuild task to the existing Knowledge workspace. Keep the task owner
mounted across Knowledge tab switches. Compare reviewed source provenance and
counts with current knowledge, using stacked cards at narrow widths. Inspection,
staging, generation, publication and retained restore remain explicit actions.
Keep keyboard focus, reduced motion and local capture/history available.

The native connection's service-presence capability controls availability, not
reviewer permission or configured source/provider readiness. Authentication and
the existing `knowledge.curator` role remain server-owned. A missing source,
disabled provider, denied role or disconnected server needs bounded guidance
and recovery; it must not disable unrelated local controls.

| Explicit action | Existing service route | Caller supplies |
| --- | --- | --- |
| Inspect reviewed source | GET `/v1/knowledge/source-preparations` | No query/body |
| Stage inspected source | POST `/v1/knowledge/source-preparations` | Version 1 and `expectedGenerationSha256` |
| Prepare embeddings | POST `/v1/knowledge/embedding-preparations` | Version 1 and `generationSha256` |
| Inspect a generation | GET `/v1/knowledge/publications` | One `generationSha256` query |
| Publish staged knowledge | POST `/v1/knowledge/publications` | Version 1, target and explicit nullable `expectedActiveGenerationSha256` |
| Restore retained knowledge | POST `/v1/knowledge/rollbacks` | The same activation shape, after explicit retained inspection |

Source, endpoint, credential, tenant, reviewer, approval, model and vector fields
cannot come from the renderer. Deployment chooses reviewed source and the
already-running provider. The renderer chooses only inspected/saved generation
references and explicit actions. It never starts or downloads a model.

## Native receipt and authority

Reuse the authenticated dispatcher and connector transport/account leases.
Check the expected authority revision before dispatch and current authority
before exposing a response. Limit response bytes and elapsed time. A cohesive
typed rebuild client and native request owner can serve these related actions;
keep endpoint construction and credential acquisition in native code.

Reject unknown or missing required fields, wrong versions/status, malformed
references/model metadata, invalid counts and responses for a different target.
Required nullable active references must distinguish JSON null from absence.
Compare inspected source/generation revision and all four descriptor counts.
Source and generation inspections report metadata; the service's complete
source/admission/vector validator remains the publication authority.

A changed activation must report its requested target as active and the
requested expected-active reference as previous active. A successful replay
reports `changed: false`, with target still active and previous-active equal to
that target; it may confirm an earlier lost reply even when the original
expected-active reference differs. Preserve this valid replay behavior.
An embedding receipt confirms prepared model metadata/chunk count for its exact
target. It does not attest provider artifacts or model quality.

## Unconfirmed writes and restore

Keep a same-owner mutating request's target and expected-active pair available
for explicit recovery. A transport failure, timeout, dropped reply, malformed
success or lease change after dispatch cannot prove that the remote write did
not commit. Never report it as successfully cancelled or undone. Finish bounded
native work or report its outcome unconfirmed; do not retry automatically.

Reinspect after source/active state changes and clear the old confirmation.
Repeat staged embedding preparation explicitly to confirm it without another
provider call when complete. Metadata inspection alone cannot establish vector
completeness. Publication and restore replay must retain the original data and
avoid duplicate activation history. Reject cross-owner late results and hide
private state immediately when the account/server changes.

After reopening, inspect the configured reviewed source or an explicitly saved
generation reference before a new decision. The current service has no retained
history list; expose a saved reference and the confirmed previous-active
reference without inventing discovery or access to another reviewer's admission.
Pruned, damaged, unpublished and unavailable generations remain refused.

## Verification boundary

Exercise strict native HTTP/auth/context behavior, real HTTP/PostgreSQL
source → stage → embeddings → publication → permission-filtered reads → restore,
and browser success/failure/recovery with deterministic fixtures. Verify a real
native-to-service journey before claiming that combined boundary. Keep those
results distinct from mock transport, hosted/native platform checks and actual
provider, enterprise, physical Windows and production qualification.

The single queue retains seven acceptance conditions and the six-reviewed-green
exact-head integration gate. This document supplies no implementation or
qualification credit and creates no second execution queue.
