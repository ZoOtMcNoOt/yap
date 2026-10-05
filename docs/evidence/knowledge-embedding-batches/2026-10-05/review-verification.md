# Shared deadline review correction

Owner: Grant McNatt. Date: 2026-10-05 UTC.

Independent read-only review of `2ea012aa60b9ee64359470242fc7550537225c57`
found a delayed-worker dispatch race. The caller checked the deadline before
starting a worker, but the worker could execute after expiry and implicitly
reopen the already closed HTTP connection. Existing database atomicity prevented
partial vector/model commits; it did not prevent late provider work.

[Original real HTTP observations](review-original.txt) reproduce one provider
POST after the caller stopped for each of four cases: delayed worker startup or
request sending, each with total deadline expiry or cancellation. The regression
uses synthetic source text and a controlled scheduling barrier against the real
owned loopback provider, clearing requests between cases.

The worker now checks shared expiry/cancellation before connecting and before
sending. HTTP automatic reopening is disabled; a connection closed during a
scheduled send cannot reconnect. The worker closes its connection on every exit,
and the caller rechecks expiry/cancellation before accepting a completed result.
Concurrent closure retains the socket reference before shutdown, so the caller
and worker cannot dereference a socket already cleared by the other closer.
Normal reasoning and token-count routes share this transport and remain covered.

All 22 provider/transport cases pass in 15.304s, including those four dispatch
races, wall-clock timeout, contained cancellation, forced-tool answers and render
requests. Ruff and formatting pass for all seven changed Python files. All 165 required SQL cases pass without skips on final source (70.464s), and all 215 governed
portable cases pass without skips or expected failures (23.617s). Final isolated-server renewal passes all 1,840 discovered cases: 1,678 passes,
162 declared platform/fixture/database exclusions and zero failures (123.887s).
Actual SQL runs separately without skips. All 30 repository contracts also pass without skips (11.118s).
Independent exact-head re-review and all six hosted jobs remain required before
integration. Prior pre-correction passes are preserved as dated observations rather
than credit for the corrected head. Actual model/capacity/enterprise qualification
and the entire roadmap remain open.


## Containment fixture corrections

The first complete server renewal stopped at an existing fake-Docker cancellation
fixture. Its 1.5-second timer fired before the fake child started, so it never
exercised the asserted kill-and-owned-cleanup path. Cancellation now follows a
marker written after the actual synthetic child starts and records resource
creation. A bounded native task using a monotonic stopwatch signals the same cancellation token; exact
container run/inspect/remove/list assertions remain intact. No product Docker
owner or production cancellation behavior changes.

The earlier Librarian fixture reused its 10-ms work timeout for the eight-worker
startup barrier. Tests now shorten only the futures work wait, retaining the
normal synchronization deadline and all timeout/cancellation/containment
assertions. The three isolated real-process/thread containment cases pass in
5.587s; full renewal includes them. Changed test regions are formatted; unrelated
pre-existing formatting in these two fixture files is preserved.
