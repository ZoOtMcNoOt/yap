# Windows export receipt assertion renewal

Owner: Grant McNatt. Date: 2026-10-05 UTC.

[Run 565](https://github.com/ZoOtMcNoOt/yap/actions/runs/37276242335) on
`d46744f7155e06524b1061d4cf3d94494fbffe22` retained the Windows rust failure:
1,393 units passed, one failed, and 12 declared fixtures were ignored.
Job `111653775606` failed
`timed_export_serializes_exact_complete_source_and_unknown_overlap_turns`.
The saved receipt correctly returned its canonical destination, while the new
test expected the uncanonicalized temporary directory spelling. Windows expands
the `RUNNER~1` alias and adds the verbatim path prefix during canonicalization.

The assertion now compares the canonicalized saved destination, retaining the
exact session identity, source hash, complete serialized turns and JSON content
assertions. Product export behavior is unchanged. The failed head receives no
green native gate credit; the corrected reviewed head requires full hosted
renewal before integration.
