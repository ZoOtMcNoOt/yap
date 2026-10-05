# Ogg FLAC import verification

Owner: Grant McNatt. Date: 2026-10-05 UTC.

Acceptance was recorded before implementation at `d5ce762f` in the
[single execution queue](../../../plans/active/2026-10-02-yap-project-hill-climb.md).
This increment reuses the locked unmodified Symphonia 0.6.1 Ogg mapper and FLAC
decoder, existing native intake/preparation/ledger owners and retained source
handles. No decoder dependency or license boundary changes.

A real synthetic two-second stereo 48 kHz Ogg FLAC fixture exposed silent audio
loss: damaging one middle page caused the original decoder to accept 82,176
source frames instead of 96,000. The complete fixture passed and missing EOS was
already refused. [Original observations](original-observations.txt) retain that
actual three-case result; the missing-ending case receives no new-defect claim.
The corrected decoder probes complete EOS for every actual Ogg container and
requires the decoded frame count to match its declared ending. Conflicting
initial-header and EOS counts refuse. Sources and unrelated files remain intact;
owned decoded plaintext is reclaimed on refusal/cancellation.

Seven added native cases pass in the current runs: stereo content and exact
source duration, mono normalization, missing EOS, damaged middle page, conflicting
header/EOS counts with valid CRC, chained/truncated streams, and cancellation
followed by a valid retry. Existing canonical-manifest and native intake/restored
catalog cases now exercise both Vorbis and FLAC, retaining original assertions.
The fixture README records exact generation commands and SHA256 hashes.

The TypeScript/Vite build passes. All 417 portable frontend cases pass, with two
declared Windows-only exclusions. Release contracts pass 67 cases with five
Windows-only exclusions; 30 documentation/license/provenance/population/workflow
contracts pass without exclusions. A local contract run refused the dirty
checkout and receives no full-suite credit; renew it on the final clean head.

The renewed full native suite passes 1,406 units (56.47s) and all 27
integrations, with 12 declared ignores and no failures. It includes the corrected
48 kHz fixture expectation and the existing settings-publication observer
synchronized with its first actual read. The previous run had 1,405 passes, one
observer scheduling failure and 12 declared ignores; that run retains no
complete-suite credit. All-target Clippy passes with `-D clippy::all` (1m43s); preexisting Linux-only
unused platform warnings remain. Hosted Windows strict warnings remain required. The initial
focused browser run had 11 passes and a timeout in the existing long cancel/retry
journey under concurrent local browser/build work. Its trace is retained under `/tmp/yap-ogg-flac-browser-original`. All 12 recording
journeys now pass (1.1m), serially after native builds with private Vite caches;
assertions and timeouts are unchanged. Complete hosted browser renewal remains
required. Source review found
no unresolved actionable issues; final immutable-head review remains required.

Product guidance names Ogg Vorbis/FLAC explicitly. Single logical audio streams
are supported; chained/multiple streams, unsupported Opus and WebM remain outside
this increment. The four-hour decode resource ceiling is an admission bound,
not qualified maximum recording duration. Synthetic tones and bridge fixtures do
not qualify actual ASR/speaker/alignment accuracy, physical Windows playback or
enterprise operation. Hosted six-job green reviewed integration follows the
saved timed speaker export, PR #208 and PR #209; the full roadmap remains active.
