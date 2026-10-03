# Accepted correction export

**Owner:** Grant McNatt. **Date:** 2026-10-03. **Status:** Six software outcomes verified in the development working tree.

Correct could recover and copy accepted revisions, but only originals had a
new-file export. **Export saved correction** now selects a destination for the
accepted revision shown in Correct, independently of server access or models.
New suggestions need explicit acceptance first. The [project goal](../../../plans/active/2026-10-02-yap-project-hill-climb.md)
stays active across every workstream.

## Ownership and preservation

The main-window command receives the original output path plus displayed
revision/hash preconditions. It accepts no renderer transcript text, revision
file path or approval claim. Existing source owners validate committed live or
published remote provenance; bounded recovery validates the entire accepted
chain and its latest current-source proof. A different latest revision fails
before the picker, including when its corrected text has the same hash.

After selection, the native worker rereads the source and accepted history. It
refuses changed source identity, missing/corrupt/staged history or a different
latest accepted revision. Exact corrected UTF-8 bytes then use the existing
new-file writer and destination checks: absolute local `.txt`, default extension,
canonical parent outside Yap data, private atomic staging and no replacement.
Originals, accepted files, existing destinations and unrelated `.part` files
remain intact. The suggested filename is `transcript-corrected-rN.txt`.

Original and corrected commands share one native export permit, held by the
worker through reading, picker and publication. Destination operations are not
abandoned on a timeout that could publish after a reported failure. The root
renderer file-action owner shares busy state across both actions and navigation;
source-bound completion guards suppress stale correction feedback. A returned
saved receipt must match the requested revision/hash. Cancellation is distinct;
failures retain the comparison and support explicit retry or history refresh.

Source-bound corrected text can differ in newline formatting from the original
plaintext artifact. Export preserves the accepted text exactly; it neither
normalizes it nor rewrites the original. Older revision selection and
corrected timing/speaker formats remain separate work.

## Acceptance

| Outcome | Development evidence |
| --- | --- |
| Trusted accepted bytes; displayed revision/hash are preconditions only | Native recovery reads real committed live-source provenance/timing and immutable accepted files; wrong/missing displayed revisions fail. Browser inspects exact native arguments without renderer text/path authority. |
| Current source/history rechecked after selection | Native cases refuse advanced revisions even with unchanged text, changed source proof, actual removed source, corrupted/missing revision files and stale staging; no export appears. |
| Exact UTF-8 and retained files | Native multilingual export retains original and both revision byte arrays, supplies `.txt`, uses mode 0600 on Unix and preserves existing/internal destinations and unrelated staging. Existing original-export checks cover the shared writer's race, alias, extension and write-failure behavior. |
| Offline action, cancellation, retry and keyboard layout | Browser cases at 360/1440 px verify saved-only action, exact preconditions, focus, cancellation, failure/retry, stale-history refresh and no horizontal overflow. Unsaved suggestions cannot use it. |
| Bounded export and source-bound feedback | Native permit case verifies one shared worker. Browser navigation/reopening retains busy state, blocks original/duplicate export and ignores late failure from an abandoned view. Misbound receipts do not claim success. |
| Layered checks and explicit qualification | Seven focused native and thirteen original/corrected browser cases pass; full desktop suites, builds and final documentation checks pass. |

## Checks

| Check | Result |
| --- | --- |
| Focused native | Seven passed: six committed-source/persisted-correction export cases and one shared worker-permit case. |
| Focused browser | Thirteen passed: eight new accepted-export cases and five existing original-export cases. |
| Full frontend | 388 passed, two existing Windows-only exclusions. |
| Full native | 1,350 unit + 27 integration passed, 11 existing model/hardware ignores. |
| Full Chromium | 169 passed, one existing Windows-only island exclusion. |
| TypeScript/Vite and Linux application | Passed; Tauri debug/no-bundle build retains 18 platform-specific warnings. |
| Documentation, dependency-license and provenance contracts | Eight passed on the final documentation update. |
| Native formatting and diff whitespace | Passed. |

Development logs are `/tmp/yap-accepted-export-{unit,native,browser,build,native-build}-renewal.log`
and `/tmp/yap-accepted-export-doc-contract-final.log`. Server code is unchanged
since [Curator's verification](../../curator-connections/2026-10-03/verification.md).
No server or model runtime is needed for this increment. These are working-tree
checks, not a reviewed release head.

Reproduce focused checks from the repository root:

```bash
source verification/cloud-env.sh
cargo test --manifest-path desktop/src-tauri/Cargo.toml --locked accepted_export
cd desktop
pnpm test:e2e accepted-correction-export.spec.ts transcript-export.spec.ts
```

## Screen review

Actual Chromium captures were inspected with reduced motion enabled:
[desktop actions](01-actions-desktop.png), [narrow failure/recovery](02-retry-mobile.png)
and [tablet saved receipt](03-exported-tablet.png). Copy/export wrap in their
saved-revision group at 360 px. Failure leaves both comparison texts visible;
refresh and retry are explicit. The 720 px success view shows the revision and
export destination without changing selection. These are UI fixtures, not native
picker or inference evidence. The action placement follows the existing
[document-reading references](../../ui-completion/2026-10-02-design-references.md)
and [shared design](../../design-refresh/2026-10-03/review.md); no new assets,
animation package or dependency was introduced.

## Qualification

Browser fixtures replace native picker responses. Native cases independently
exercise committed source/revision reads and real filesystem publication; the
registered command and picker compile in Linux. Actual Windows picker/focus,
NTFS no-replace/link/ACL behavior and native clipboard/window interaction still
need their target checks. No correction model was run; this verifies export of
already accepted text, not the quality of its suggestion or production release.
