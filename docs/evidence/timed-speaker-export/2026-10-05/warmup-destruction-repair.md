# Cancelled warmup destruction ownership repair

Owner: Grant McNatt. Date: 2026-10-05 UTC.

[Run 569](https://github.com/ZoOtMcNoOt/yap/actions/runs/37278695798) on
`65029dd42b16c67daa1e12883a992496789432b0` passed five required jobs and failed
native job `111661477731`: 1,393 units passed, one failed, 12 declared fixtures
were ignored. `clearing_idle_warmup_cancels_and_waits_for_a_loading_model`
observed cleanup returning success before its model destructor completed.
This is a real ownership race, not a timing-only test failure. The original
Windows export canonical-path assertion was corrected separately and is retained.

The cancelled loading branch published Empty while its result remained owned by
a function argument. Rust released the local mutex guard before destroying that
argument, allowing a clearer to observe no remaining owner and return success.
Acceptance was committed at `affb15c9` before this production repair.

The repair tracks DiscardingLoad until destruction finishes on the loading
worker, outside the state mutex. Bounded cleanup waits on that owner; new warmup
requests refuse adoption during disposal. Successful destruction alone publishes
Empty. A destructor panic retains the fence and reports incomplete cleanup.
The independent ready-model retirement owner remains separate because it can
coexist with a later load. Existing loading reentry remains available before
disposal begins.

A deterministic blocking destructor regression requires bounded cleanup to time
out while destruction is held, refuses duplicate loading, then allows successful
cleanup and a successor after release. A panic regression retains the fence.
The original failing test now waits for acknowledged cancellation rather than
assuming another thread started within 50 ms.

All 30 focused lifecycle cases pass without skips on corrected
`12088dea5eec1bc41f9cd71fd6cff828c2c73832` (2m13s compilation, 2.09s behavior).
Independent read-only exact-head review reports no actionable findings.
[Run 572](https://github.com/ZoOtMcNoOt/yap/actions/runs/37281343011) passes all
six hosted gates and their unchanged-checkout guards on that reviewed head.
Windows native verification passes 1,396 units and all 27 integrations, with
12 declared fixture ignores and strict Clippy. [Integration](integration.md)
records actual merged main, preserved tested tag, fetched-tree equality and
completed branch/worktree retirement. Failed observations receive no green gate
credit. Synthetic model owners qualify lifecycle behavior only; actual model,
physical Windows/RDP and enterprise qualification remain separate.
