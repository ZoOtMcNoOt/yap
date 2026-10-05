# Bounded reviewed embedding batches

Owner: Grant McNatt. Date: 2026-10-05 UTC.
Status: six of seven local software outcomes verified; reviewed integration
is pending. PR #208 must complete its independent review
corrections and integration before this increment is integrated.

The previous provider refused a valid 65-chunk generation before any request.
Original provider regressions also exposed the whole-generation chunk/byte limit
and duplicate chunk identities overwriting entries. The implementation now
preflights at most 1,024 unique nonempty chunks and 4 MiB of UTF-8 text, refuses
any individual chunk exceeding 256 KiB, and packs exact stored text into ordered
requests of at most 64 chunks and 256 KiB. Indexed responses map to the exact
compiled IDs even when the provider returns each batch in reverse order.

The current bounded loopback transport supplies one configured total deadline
for every batch. Later requests receive only the remaining time. The existing
atomic ledger writer receives only a complete validated map; a failed later
response, total timeout or audit refusal cannot commit partial vectors/model
metadata, publish knowledge or alter source and activation history. Complete
same-owner preparation replay still uses no provider requests. Published vectors
remain immutable.

Actual checks:

- All 165 required HTTP/PostgreSQL cases across 27 modules pass with zero skips
  in 102.644s, using owned digest-pinned PostgreSQL 17.11/pgvector 0.8.7.
- The 65-chunk source journey runs two provider requests of 64 and 1 inputs,
  stages and prepares all chunks, publishes with expected-active authority,
  verifies Alice's vector/HTTP reads and Bob's denied visibility, then restores
  the retained generation. Preparation replay performs no provider call.
- Later invalid output, a shared 1-second deadline and audit failure preserve
  full database snapshots; explicit retry recovers. Raw reviewed files remain
  byte-identical.
- Full isolated Ubuntu discovery: 1,839 total, 1,677 passes and 162 declared
  platform/fixture/database exclusions in 131.010s. Actual required SQL cases
  run separately without skips. The complete renewal has zero failures.
- All 214 governed portable cases across 32 modules pass without skips or
  expected failures in 42.626s. All 21 provider/transport cases previously passed
  in 13.673s. Ruff and formatting pass for seven changed Python files.

The first large-source fixture appended 63 paragraphs to one existing chunk,
producing 64. Its 65-chunk assertion failed; adding the intended 64 paragraphs
corrected the fixture. The failed partial SQL run receives no full-suite credit.
A portable run without loopback permissions was interrupted and renewed with
local HTTP enabled. The default cloud server script expected absent home caches;
the established isolated runner instead mounts the preserved workspace caches.
The first isolated run then stopped at an existing 10-ms Librarian synchronization
fixture while broad suites were running. The complete renewal passes with zero failures; the original partial run is
retained and receives no full-suite credit. No unrelated product or fixture
behavior was changed to obtain that result.

These are deterministic identities and synthetic vectors against actual HTTP
and PostgreSQL. Actual embedding quality/provenance, realistic provider capacity,
enterprise identity and physical-platform promotion remain open. No dependencies
or model assets are acquired. The entire roadmap stays active.
