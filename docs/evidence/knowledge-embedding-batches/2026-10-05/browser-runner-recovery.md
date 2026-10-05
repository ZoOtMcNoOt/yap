# Browser runner resource recovery

Owner: Grant McNatt. Date: 2026-10-05 UTC.

The original frontend job on reviewed head
`af3a65c8f31fde29556d7bc126fb4e1bdf759af6` retained one startup timeout.
The complete same-head diagnostic renewal in
[run 564 attempt 2](https://github.com/ZoOtMcNoOt/yap/actions/runs/37272605309)
ended with 249 passing cases and two failures. Job `111650177499` failed the
initial navigation in accepted-correction-recovery and playback-authorization
with `net::ERR_NO_BUFFER_SPACE`. Both traces contain only the first loopback GET,
status -1, approximately 12/16 ms; neither reaches application code. Blank
screenshots and traces are retained in hosted artifact `11330069860` and outside
Git in the downloaded artifact. No complete-suite pass is credited.

The traces establish browser/loopback resource failure; they do not identify
which Windows networking resource was exhausted. Development serving loads the
unbundled module graph and an HMR connection into every isolated browser context.
The correction builds and serves a separate bundled browser-test artifact,
reducing those requests and removing development-server transformation/HMR work.
It retains both fixture HTML entries and the development-only live-overlay
preview in the test artifact. The normal shipped build stays unchanged.

The artifact has its own ignored output directory, a fresh build before serving,
strict loopback port ownership and the existing explicit server-reuse option.
All browser cases, assertions, per-test timeouts, one worker, failure artifacts
and final exact-head guards remain. Existing frontend contracts also verify the
fixture/preview boundary. Bundled fixture URLs, preview behavior and complete
Windows-suite renewal must pass before integration; request reduction alone
does not prove this resource failure resolved.
