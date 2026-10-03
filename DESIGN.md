---
version: alpha
name: Yap Clear Workbench
description: A private desktop transcription design system for Yap.
colors:
  ink: "#20242C"
  muted-ink: "#626977"
  quiet-ink: "#626977"
  canvas: "#EEF0F4"
  surface: "#FCFCFE"
  surface-muted: "#F4F5F8"
  border: "#DDE1E9"
  border-soft: "#E8EBF1"
  primary: "#5143A0"
  primary-hover: "#443687"
  primary-soft: "#E9E5F7"
  accent: "#E9E5F7"
  success: "#034F46"
  warning: "#B45309"
  danger: "#B91C1C"
typography:
  headline-lg:
    fontFamily: ui-sans-serif
    fontSize: 36px
    fontWeight: 650
    lineHeight: 1.15
    letterSpacing: 0
  headline-md:
    fontFamily: ui-sans-serif
    fontSize: 22px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: 0
  body-md:
    fontFamily: ui-sans-serif
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: 0
  body-sm:
    fontFamily: ui-sans-serif
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: 0
  label-md:
    fontFamily: ui-sans-serif
    fontSize: 13px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: 0
  caption:
    fontFamily: ui-sans-serif
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1.35
    letterSpacing: 0
rounded:
  sm: 8px
  md: 12px
  lg: 24px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  xxl: 48px
  app-margin: 20px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: 10px 14px
    typography: "{typography.label-md}"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    borderColor: "{colors.border-soft}"
    rounded: "{rounded.md}"
    padding: 10px 14px
    typography: "{typography.label-md}"
  card:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.border-soft}"
    rounded: "{rounded.md}"
    padding: "{spacing.md}"
  status-pill:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
    borderColor: "{colors.primary-soft}"
    rounded: "{rounded.md}"
    typography: "{typography.label-md}"
---

# Yap Design System

## Overview

Yap is a private desktop transcription app for people with recordings, meetings,
voice memos, interviews, and, in the planned format expansion, video files sitting on their machine. It should
feel like a polished consumer utility: calm, direct, private, clear, and fast to
understand. The product language borrows practical strategies from Wispr Flow
and Figma-style tools: sparse navigation, a soft canvas, one generous work
surface, compact status pills, and document-like transcript surfaces.

The core product promise is "drop audio, get text." The interface should make
the current file and transcript feel more important than the model, auth state,
or runner details. Technical setup belongs in a details drawer or secondary
status area unless something needs attention.

Executable color tokens live in [styles.css](desktop/src/styles.css). Reviewed
[Mobbin screens, flows, and sections](docs/evidence/ui-completion/2026-10-02-design-references.md) inform reading, citations, and Help disclosure.

Use route labels sparingly but confidently. Users should understand whether work
is private on this device or running on the org-owned server without the app
sounding like infrastructure tooling.

See the [current screen review and motion evidence](docs/evidence/design-refresh/2026-10-03/review.md)
for the shared-system refresh and the remaining native/Wispr research boundaries.

## Colors

The palette uses cool neutral surfaces and purple actions. Mint belongs to voice
activity; glass belongs to compact floating controls. Reading surfaces stay opaque.

- **Ink (`#20242C`):** Primary text, transcript text, and important labels.
- **Canvas (`#EEF0F4`):** App background. It should feel soft without turning
  into a decorative landing page.
- **Surface (`#FCFCFE`):** Primary panels, cards, transcript editor, and sheets.
- **Primary Purple (`#5143A0`):** Main actions, selected tasks, and focus.
- **Accent Lavender (`#E9E5F7`):** Review affordances and occasional emphasis;
  never compete with the primary action.
- **Warning and Danger:** Reserved for setup, auth, or failed transcription.

The [original speech-and-wave mark](desktop/public/yap-mark.svg) is the canonical
logo source. Desktop installer and browser icons are rasterized from it with the
locked Tauri CLI; see [icon regeneration](desktop/src-tauri/icons/README.md).

## Typography

Use the system sans-serif stack for the app shell and operational UI. Inter is
used when installed; Yap does not fetch a font at runtime. A serif display treatment is
allowed only for the large drop hero headline, where it gives the product a
friendlier editorial moment without spreading into controls or dense surfaces.

- **Headlines:** Short, concrete labels such as "Drop recordings" or
  "Transcript ready."
- **Body:** Plain operational copy. Avoid explaining the whole product on screen.
- **Labels:** Sentence case except compact status chips. Do not use decorative
  letter spacing.
- **Transcript text:** Comfortable long-form reading, at least 15px with a loose
  line height.

## Layout

The primary layout is a clear workbench with one obvious action at a time.

- Home: recent transcripts or a direct recording action. Transcribe owns the
  drop zone, queue, and adjacent transcript workspace on wide screens.
- Running state: the active file card should show progress, elapsed time, and a
  clear cancel/remove path.
- Done state: readable transcript text with nearby copy/open/export/reveal and a
  direct correction action. Export saves the original as UTF-8 text to an
  explicit new destination; the action toolbar wraps without horizontal scroll.
- Correct: distinguish saved accepted revisions from new suggestions. Reopened
  revisions remain readable, copyable and exportable offline. Saved-correction
  export sits beside its copy action, wraps on narrow windows and retains focus
  on cancellation/retry; it stays distinct from original export. Short columns fit
  their text on narrow windows, while long transcripts retain bounded scrolling.
- Settings/status: model, auth, runner, output path, and logs live in a secondary
  area. They should not dominate the first screen.
- Personalization: trusted personal/team/organization scope selection exposes
  read-only permissions and keeps drafts bound to one native connection and scope.
  Preferred spellings live in a readable, paged list with
  contextual edit/delete actions and an inline form. Failed writes retain the
  draft; conflicts show the latest saved term before an explicit resolution.
  Delete uses confirmation; closing or switching Settings does not resubmit work.

Use an 8px rhythm. The Tauri window enforces a minimum of 1122×740 (default
1122×760; see `desktop/src-tauri/tauri.conf.json`). Layout targets that floor.
Responsive single-column at mobile widths (e.g. 360px) is not a current target
unless `minWidth` is lowered later. Nothing in the main flow should require
horizontal scrolling at the enforced minimum size.

## Motion & Stability

Motion should feel quick, but it cannot move the target out from under the
cursor.

- Animate `transform` and `opacity` before layout dimensions.
- Keep hover hit areas stable while the visible control morphs inside them.
- Use one owner for geometry: either React lays out an in-window surface, or
  Rust/Tauri owns the native window frame.
- Test motion during the transition, not only after it settles.
- Respect `prefers-reduced-motion`, including changes while the app is open.
- Use the shared 120ms response / 200ms settle tokens. Reveal uses a restrained
  overshoot; interruptible transitions always settle to the latest state.
- Animate transform and opacity for island reveal and waveform activity. Sidebar
  resizing happens once, without continuously reflowing the reading surface.
- Keep the island blur bounded to its small native surface. Increased contrast
  or reduced transparency uses an opaque surface; no experimental GPU flags.
- Stop the waveform clock while hidden or reduced motion is selected.
- Measure target compositor performance separately from browser fixture checks.

Do not resize native windows from multiple layers, animate hit-area width on
hover, or use decorative motion that changes the user's target.

## Elevation & Depth

Use tonal depth instead of heavy shadows. Panels sit on the canvas with soft
borders and small shadows only where a surface is interactive or draggable.

The drop zone may feel slightly tactile when active: brighter border, subtle
surface tint, and a lifted shadow. Avoid decorative blobs, oversized gradients,
or effects that make the app feel like a landing page.

## Shapes

Use soft but disciplined rounded corners.

- App workspace and drop hero: 28px.
- Core cards and transcript surfaces: 12px.
- Icon buttons and compact controls: 8px.
- Pills: full radius only for tiny status or privacy badges.

Do not mix sharp and heavily rounded components in the same view.

## Components

**Drop Zone**

The drop zone is the first-run hero. It should include a clear icon, one direct
heading, supported formats in small text, and a privacy/local badge. During drag,
the whole surface should visibly respond.

**File Cards**

File cards show the filename first, then status or destination. Use status color
sparingly: queued is neutral, running is warning, done is teal, error is red.
Every completed card should have a reveal/open action.

**Transcript Preview**

The transcript is the reward state. It should use a readable text area or editor
surface with copy, export, and reveal actions nearby. Future speaker labels or
timestamps should be visually quiet and scannable.

**Buttons**

Use one primary button per screen state. Secondary actions are bordered buttons
or icon buttons with tooltips. Destructive actions stay icon-only when the label
is obvious, with a tooltip and accessible title.

**Status And Setup**

Technical status should be compact. Show "Ready", "Needs attention", or
"Transcribing locally" in the main UI. Put model names, auth paths, and runner
details behind disclosure unless an error requires them.

## Do's and Don'ts

- Do make the transcript or next user action the visual center.
- Do say "Private on this device" or "Org server" instead of exposing
  implementation details.
- Do keep the app usable at the Tauri minimum size (1122×740) with no overlapping controls.
- Do use icons for actions like remove, reveal, copy, settings, and export.
- Don't lead with model IDs, Python paths, auth mechanisms, or RTX jargon.
- Don't make the app look like a dashboard when it is a file-to-transcript tool.
- Don't use giant hero copy, marketing sections, nested cards, or decorative
  gradient blobs.
- Don't use more than one primary accent in the same screen state.

Knowledge Connections uses human topic titles, a bounded directed neighborhood and an equivalent keyboard-readable relationship list. Source authority and proof stay visible during exploration; proposals remain separate. Narrow task navigation scrolls horizontally, and Connections removes repeated panel headings. [Current screens and checks](docs/evidence/knowledge-connections/2026-10-03/verification.md).
