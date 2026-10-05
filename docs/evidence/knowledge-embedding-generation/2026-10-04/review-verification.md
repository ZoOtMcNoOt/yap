# Embedding review corrections

Owner: Grant McNatt. Date: 2026-10-04. Status: verified locally; exact-head
hosted renewal pending. This is the dated local baseline;
[integration evidence](integration.md) supersedes its pending gate with the
actual reviewed six-green-job merge.

Review identified valid JSON integers too large for Python float conversion.
A local HTTP provider returning 401-digit vector values reproduced an unhandled
OverflowError; the real authenticated HTTP request ended with RemoteDisconnected
instead of its documented refusal. [Provider](original-overflow-provider.txt) and
[HTTP](original-overflow-http.txt) observations retain both actual failures.

The existing shared vector serializer now translates float-conversion overflow
to its normal content-free ValueError. The service returns its ordinary 409
refusal, preserving every source/projection/active/history/audit row. Existing
provider and HTTP cases now exercise this actual numeric payload; the population
is unchanged. All 161 required real PostgreSQL cases/26 modules pass without
skips (66.093s); all 209 portable/32 modules pass without skips (23.298s).
Full isolated Ubuntu discovery passes 1,672 with 158 declared exclusions
(1,830 total, 118.159s), with required SQL executed separately. Ruff and changed
formatting pass. The numeric fix applies to all existing vector consumers.

Review also identified stale summary and lower-section integration descriptions
in current status and the single queue. PR #205 and #206 now consistently record
their actual six-green-job merge receipts and preserved exact heads. Only the
embedding increment remains awaiting its own exact-head integration. Corrected
renamed section links and retained all original outcomes and historical evidence.

The fresh successor also restored the user-owned native libraries and verified
the official Sherpa archive checksum using the repository setup steps. The actual
Linux native build at main `d2d3685b` passes all 16 export-file cases (no skips),
with the unchanged platform-specific unused-code warnings. This focused native
result verifies toolchain/file ownership, not a renewed full native suite or
physical Windows/model/enterprise behavior. Fixture vectors still do not qualify
embedding quality or provider artifacts.
