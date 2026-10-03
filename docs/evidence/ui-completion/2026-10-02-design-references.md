# UI design references

**Owner:** Grant McNatt. **Reviewed:** 2026-10-02; shared terminology references added 2026-10-03.

References inform the [hardware-free completion goal](../../plans/completed/2026-10-02-hardware-free-product-completion.md). Preserve Yap's identity and native ownership; adapt interaction patterns without copying brand assets or unrelated product behavior.

## Screens

| Reference | Observed pattern | Yap disposition |
| --- | --- | --- |
| [Dropbox Dash document view](https://mobbin.com/screens/c5859a8e-f817-45fe-9b87-684dc71cba95) | A dedicated reading pane with document actions beside the text. | Keep reading comfortable and add a direct correction action to the transcript toolbar. |
| [Microsoft Copilot references](https://mobbin.com/screens/e631b279-cfc4-4c1c-85c9-f06c838b8df2) | Numbered references are grouped beneath the answer, with source names distinct from surrounding detail. | Use consistent, numbered citations; show readable source names and exact quotes, with revision/range details behind disclosure. |
| [AirOps citation analytics](https://mobbin.com/screens/bcae9024-b9a6-4fe1-a5ec-0e16cddc74dd) | A dense URL/brand analytics table with filters and export. | Reviewed, but not a fit for Yap's transcript and source-reading tasks. |
| [Grammarly personal dictionary](https://mobbin.com/screens/e9ce3028-a1fc-4f3b-af9c-5acb4425b423) | Dictionary settings place a small add-word form above readable saved words and contextual deletion. | Personalization uses a paged list and an inline preferred-spelling/variant form, with explicit version conflicts and deletion confirmation. |
| [ElevenLabs pronunciation dictionary](https://mobbin.com/screens/aafe5a0f-ea85-4ef7-8cb6-0537cdfd2d28) | An empty rules pane explains the next action and offers a visible add-rule button. | Keep an actionable empty personal-term state. Voice/pronunciation rules and administrator labels do not apply to Yap's personal spelling contract. |
| [WorkOS workspace settings](https://mobbin.com/screens/478c4874-c5a5-4aa6-90aa-5f1153f8c0e2) | A workspace context sits above team details; the member table makes roles visible. | Use a trusted scope label and explicit read-only guidance, with contextual editing actions. Membership administration stays with the organization. |
| [VEED team privacy settings](https://mobbin.com/screens/579b1621-bdaf-4e88-8e1b-70898c15f94b) | Team settings group privacy defaults and editor access beside short explanations. | Reviewed for permission clarity; do not introduce renderer-owned access toggles or unrelated privacy settings. |

## Flows

| Reference | Inspected steps | Yap disposition |
| --- | --- | --- |
| [Fireflies: starting a voice recording](https://mobbin.com/flows/2e0c4e46-3edd-4f2e-9477-b472092dcfee) | Previewed Home, explicit meeting-language confirmation, and the active timer with Pause/Stop (steps 1, 5, 8 of 8). | Keep language choice explicit before work begins and cancellation/status visible. Yap retains separate local dictation and organization-server routes. |
| [Cofounder: document detail](https://mobbin.com/flows/d92842d7-885c-4606-a62c-54b2c6fbabbf) | Inspected all three screens: contextual document reading and switching between Preview and Source. | Keep the selected source through review and correction; preserve readable original text alongside proposed changes. |
| [Dovetail: adding custom vocabulary](https://mobbin.com/flows/5f489f1f-aa60-4b13-abe5-28783a922706) | Inspected returned previews 1, 3 and 4 of 4: transcription settings, the focused vocabulary field, and a saved vocabulary chip. | Keep adding vocabulary contextual and retain the list alongside editing. Yap additionally requires explicit variants, locale, sensitivity and conflict recovery; the reference's accuracy claim is not evidence for Yap. |
| [Grammarly: creating a team dictionary](https://mobbin.com/flows/8bbbf2fe-098e-4a3d-a3df-9ec6f8fc0faa) | Inspected returned previews 1, 3 and 5 of 5: actionable team-dictionary empty state, focused add-entry dialog, and populated dictionary list. | Keep shared terminology contextual to the selected scope and retain readable entries; Yap additionally requires locale, sensitivity, variants and explicit version-conflict recovery. |

Only the returned preview steps were visually inspected; a full flow inspection is not claimed where intermediate screenshots were absent.

## Website sections

| Reference | Observed pattern | Yap disposition |
| --- | --- | --- |
| [Farm Minerals FAQ](https://mobbin.com/sites/sections/82a675c9-a7cd-4930-9fb2-d94fcefe242f) | Short questions expand into an answer within the section. | Use question-based disclosure for setup, routing, storage and review guidance in Help. |
| [KÖPPEN FAQ](https://mobbin.com/sites/sections/09028542-9505-40c7-b979-f26d42605598) | A compact list of questions keeps most answers collapsed. | Keep common controls visible and detailed explanations optional. The marketing imagery and commerce actions do not apply. |

The connected Mobbin interface provides screen, flow and website-section search. This review used all three. Links point to canonical Mobbin references; third-party screenshots and branding are not shipped in Yap.
