# Desktop rebuild review corrections

Owner: Grant McNatt. Date: 2026-10-05 UTC.

Independent read-only review examined exact head
`4369712e27c4c2a325a9deaa86bfaf84762fe94e`. All six hosted jobs passed
in [run 561](https://github.com/ZoOtMcNoOt/yap/actions/runs/37267159637),
but review found three actionable issues. That green run does not qualify the
subsequent corrections for integration.

Native authorization failures now retain `identityChanged`, including silent
refresh failures and invalidated response leases. Transport failures retain
`unavailable`. Both conservatively report write uncertainty when dispatch may
have occurred. The renderer clears private source details, inspected generation,
activation, saved references and recovery requests when identity changes, even
without a connector-revision event.

Staging must match the originally inspected generation, source revision and all
four counts. Mismatching success receipts remain unconfirmed and cannot replace
the inspected source. Activation recovery now retains those immutable descriptors
alongside the exact original request and validates every publication/restore
replay against them. Renewed active references and deployment source paths do not
change that binding. A dropped reply is not evidence that a write rolled back.

[Original observations](review-original.txt) retain the failing native identity
regression and three failing browser cases. The existing nine browser cases
passed before correction. Corrected local checks pass: 1,393 native units and all 27 integrations,
12 declared ignores; the exact built-native HTTP/PostgreSQL journey separately
passes with one test and zero skips (0.65s). All 13 rebuilding browser cases
pass (2.7m), including staging and publication/restore replay regressions and
identity clearing without a revision event. All 409 frontend unit cases pass
with two Windows-only exclusions; TypeScript/Vite builds. Strict Clippy passes
(37.51s), and all 30 documentation/license/provenance/population/workflow cases
pass without skips. Formatting subsequently changes whitespace only.

Exact-head independent re-review and six renewed green jobs remain required
before merge.

Independent re-review of `20fa6779577f7f0a2bd1e272ae702ba30bdeb607`
found no unresolved actionable findings. Run 562 passed five jobs and all 411
Windows frontend units, but the complete serial browser suite reached the
25-minute job limit after 199 passing case markers. It reported no test failure before
cancellation and receives no complete-suite credit. Increase only the frontend
job ceiling to 40 minutes; preserve all 251 cases, one worker, 20-second test
timeouts, assertions and exact-checkout guards. Renew all six jobs on the changed
head; run 562 cannot qualify it for integration.

The fixtures use synthetic identities and vectors. They do not qualify actual
provider quality, enterprise identity or physical Windows operation. The entire
project roadmap remains active.
