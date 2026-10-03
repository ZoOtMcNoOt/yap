# Yap design refresh

Owner: Grant McNatt. Reviewed 2026-10-03. This is a first shared-system increment;
the full UI and knowledge-connections work remain in the [project queue](../../../plans/active/2026-10-02-yap-project-hill-climb.md).

## Screen review

Captured from the current app with native-boundary fixtures in Linux Chromium.
Each image was opened and inspected. A blank first island capture was rejected
and recaptured after its reveal settled. These are synthetic records, not customer data.

1. **Home — healthy reading structure, refreshed identity and hierarchy.** The
   original tiny illustrated logo lost detail, and neutral active navigation was
   difficult to distinguish from hover. The new speech/wave vector and purple
   selection clarify both. The main surface stays opaque and readable.
   [Before](before/01-home.png) · [After](after/01-home.png).
2. **Knowledge — healthy task navigation, connection exploration still missing.**
   The introduction repeated itself before the form. Shortened copy and grouped
   tasks make the first choice clearer. In this recorded design pass tasks wrap, retain drafts and support
   arrow-key navigation; unavailable-server recovery remains explicit.
   [Before](before/02-knowledge.png) · [After](after/02-knowledge.png).
3. **Settings at 720×520 — usable with vertical scrolling.** Shared colors improve
   text separation; form boundaries were strengthened after contrast measurement.
   This frame shows the top of the scrollable panel, not the entire settings flow.
   [Before](before/03-settings-narrow.png) · [After](after/03-settings-narrow.png).
4. **Top-edge island — healthy geometry and controls, target compositor unqualified.**
   Keep the hanging tab, reveal, stable native frame and 40px actions. Dark glass
   and mint voice activity distinguish Yap. Increased contrast/reduced transparency
   use an opaque surface. Reduced motion responds while the app is open.
   [Before](before/04-island.png) · [After](after/04-island.png).

Screenshots alone do not establish accessibility compliance, motion performance
or native hit testing. The browser checks exercise focus, keyboard actions,
reversal, preference changes, narrow layouts and rendered contrast.

## References inspected

| Reference | Observed evidence and decision |
| --- | --- |
| [Grok voice screen](https://mobbin.com/screens/5b28e79b-ddd9-4878-b42e-411826249478) | Sparse content with a compact bottom control surface. Borrow bounded control grouping; keep Yap's top-edge island. |
| [Copilot voice screen](https://mobbin.com/screens/12555865-9340-476e-a3ef-bc2f8ccdb8a5) | Three compact controls below a clear listening label. Preserve explicit state and stable primary actions. |
| [Evernote linked-note flow](https://mobbin.com/flows/9559505c-631b-4e8b-9782-15f42223ab89) | Inspected returned steps 1, 3 and 5: original note, new linked note, return to original with link. Connections should preserve source context and a return path. The unreturned intermediate steps were not audited. |
| [Wispr Flow hero](https://mobbin.com/sites/sections/cc8c2464-444f-40ff-bf96-bf01f747311d) | Expressive photography and serif headline with two calls to action. Marketing reference only; it does not expose the desktop application. |
| [Wispr Flow features](https://mobbin.com/sites/sections/57b66fab-f7e0-4ea1-bec6-9f6ad9b91a59) | Four separate capability cards. Use short purpose-led explanations rather than repeating a product overview. |
| [Liquid Glass React README](https://github.com/rdev/liquid-glass-react/blob/master/README.md) and [MIT license](https://github.com/rdev/liquid-glass-react/blob/master/LICENSE) | Documents refraction/elasticity and partial Safari/Firefox support. No code or assets imported; no live demo or performance audit claimed. |
| [Liquid DOM README](https://github.com/AndrewPrifer/liquid-dom/blob/master/README.md) and [MIT license](https://github.com/AndrewPrifer/liquid-dom/blob/master/LICENSE) | Documents WebGPU and experimental HTML-in-Canvas requirements. Keep this exploration out of the current runtime until there is a supported, measured use. No code/assets imported or live rendering audit claimed. |

The direct public Wispr site/changelog, Apple material guidance and GitHub HTTP
requests were blocked by the cloud proxy (403). GitHub connector reads succeeded.
Mobbin's Wispr screen search returned other apps; they are not Wispr screenshots.
The latest Wispr desktop UI and Apple's current guidance therefore remain research
gaps. No claim that Yap improves on their current native implementation is made.

## Implementation and motion

- [Shared tokens](../../../../desktop/src/styles.css) define cool neutrals, purple
  actions, mint voice activity, 120ms response and 200ms settling.
- [Original vector mark](../../../../desktop/public/yap-mark.svg) is the source for
  UI/browser/desktop installer icons; [regeneration](../../../../desktop/src-tauri/icons/README.md)
  uses the locked Tauri CLI. No mobile-generated assets are retained.
- Removed the sidebar's GSAP effect, persistent layer hints, and width tween.
  Resizing no longer continuously reflows the reading surface; the wordmark
  transitions inside it. Existing GSAP remains for interruptible island content.
- The waveform paints fixed-height bars with transforms, outside React's render
  loop. Its clock stops on document visibility loss and reduced motion, and resets
  its timing origin when resumed. No recording state is changed by that lifecycle.
- Kept FreeFlow attribution and upstream evidence; renewed only local integrity
  hashes for edited derived files. Shortened historical implementation commentary.
- Retired the pixel baseline for the superseded island palette rather than
  labeling a Linux capture as Windows evidence. Geometry/focus/motion tests remain;
  target visual/compositor qualification still needs Windows.

The [three-second settled-waveform diagnostic](motion-profile.json) observed zero
layouts, zero layout duration and no long tasks; script time was about 20ms and
total task time about 90ms. This sample includes observer overhead and synthetic
audio. It is not an FPS, GPU, battery or Windows-compositor certification.
CSS backdrop filtering covers pixels available within the WebView; native desktop
refraction/vibrancy is not implemented or qualified by this increment.

Text contrast measured 5.38:1 for muted text on the reading surface, 4.84:1 on the
canvas, and 7.70:1 for purple on the reading surface. The initial input border was
1.50:1; the stronger token is checked against the actual rendered form. This is
focused contrast evidence, not a whole-product WCAG conformance claim.

## Acceptance and verification

**Coverage: 7/7 software outcomes for this shared-system increment.** This does not
score the full UI or qualify the target platforms.

| Outcome | Result |
| --- | --- |
| Current before/after screen review and references | Four inspected steps; Mobbin screens, flow and sections, plus GitHub runtime/license review. Direct latest-Wispr/Apple gaps are named above. |
| Coherent tokens and original icon family | Vector source, browser icons and all current desktop installer icons use the same mark; no new dependency. |
| Rendered text/form contrast | Browser assertions verify text at least 4.5:1 and input boundaries at least 3:1 on their actual surfaces. |
| Responsive Knowledge tasks and preserved journeys | Keyboard navigation fits 360×640, 720×520 and 1440×900; existing draft/recovery journeys pass. The native minimum size is separately documented. |
| Island controls and preference changes | Geometry, reversal, stable controls, announcements, live reduced-motion changes and opaque increased-contrast mode pass. |
| Bounded motion and simpler ownership | Removed sidebar GSAP/width tween; visibility/reduced-motion pause tests and the diagnostic support the waveform implementation. Native compositor remains unqualified. |
| Applicable regressions and reproducible builds/docs | Full frontend/browser checks, TypeScript/Vite/native app builds, dependency/provenance and documentation checks pass. |

Verification commands used the [cloud shell](../../../runbooks/cloud-development.md):

- `pnpm --dir desktop test`: 388 passed, two declared Windows-only skips.
- `pnpm --dir desktop test:e2e`: 116 passed, one declared Windows-only skip.
- Focused initial design/island/workspace/knowledge check: 44 passed, one skip;
  the full run additionally covers the later contrast and visibility cases.
- `pnpm --dir desktop build`: TypeScript and production Vite build passed.
- `CARGO_BUILD_JOBS=1 pnpm --dir desktop tauri build --debug --no-bundle`:
  Linux native app build passed, with 18 existing platform-unused-code warnings.
- Documentation truth, dependency license and provenance contracts: eight passed.
- `git diff --check`: passed.

No Rust execution path changed in this increment; the preceding native 1,320 unit
and 27 integration results remain the dated shared-terminology baseline.

Model quality, physical Windows interactions, OS glass, enterprise identity and
production knowledge/model round trips remain separate qualification gates.

The subsequent [connections increment](../../knowledge-connections/2026-10-03/verification.md) adds the fifth task, changes narrow task navigation to a horizontal scroll strip, and removes repeated heading copy in Connections. The four screenshots above retain the original refresh baseline.
