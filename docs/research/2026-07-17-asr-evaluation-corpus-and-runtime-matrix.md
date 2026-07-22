# ASR evaluation corpus and runtime qualification

**Date:** 2026-07-17
**Status:** executable evaluation contract and focused runtime proof in progress;
not complete promotion evidence

**Serving amendment (2026-07-21):** ADR 0025 replaces the common Triton
candidate with a Cohere vLLM gate and a separate Nemotron NeMo streaming gate.
The runtime plan and current requirements below follow that split. Later Triton
measurements are retained only under an explicit historical-evidence heading.

## Decision

Yap needs separate, reproducible gates for transcript quality and runtime
behavior. The repository currently contains one licensed, clean, short English
LibriSpeech fixture. The existing multilingual spike and eight-fixture model
comparison are useful design evidence, but neither is a checked-in,
representative qualification suite. Repeating the short fixture to create a
long WAV measures some runtime behavior; it does not establish long-form
accuracy, chunk ordering, meeting quality, or robustness.

No public speech corpus is assumed to provide literally perfect ground truth.
Some established corpora disclose known reference errors, and transcript
normalization choices can materially change WER. Yap therefore uses three
reference tiers:

1. **Upstream reference:** the immutable transcript supplied by the corpus,
   useful for comparability but carrying the source's documented limitations.
2. **Yap adjudicated gold:** a bounded, hash-frozen subset independently heard
   by two reviewers, resolved by an adjudicator, and published only as private
   evaluation material. Alternative valid renderings and inaudible regions are
   explicit. `Gold` means the accepted revision, not an absolute claim that a
   human reference is infallible.
3. **Approved use-context holdout:** consented, governed, domain-representative
   recordings that were not used to select or tune the candidate. A public
   medical mock corpus cannot substitute for an eventual Medtronic-approved
   holdout or authorize collection of employee, patient, customer, or meeting
   audio.

Test-split identity is not proof that a pretrained model never saw the audio.
Each case is therefore model-revision-specific and records one exposure state:
`known_training`, `known_evaluation`, `likely_exposed`, `unknown`,
`contractually_excluded`, or `created_after_model_freeze`. Only the last two may
support an independent promotion claim. Public sets with any other state remain
comparators and regression detectors. NVIDIA explicitly lists FLEURS, Common
Voice, and MLS in Nemotron 3.5's training and evaluation data; Cohere discloses
aggregate curated hours but not enough corpus identity to treat a public set as
clean. The decisive Yap Reality Set must be recorded after the exact candidate
revisions are frozen, kept sealed from tuning, and retired from independent use
once its examples influence implementation.

An exposure decision covers the candidate checkpoint's full lineage: base
pretraining, continued training, adapters, fine-tunes, distillation teachers,
quantized/exported derivatives, and any later Yap tuning. Open-source
availability makes a corpus easier to train on, not cleaner for evaluation.
Derived, denoised, re-encoded, mixed, or
augmented copies inherit the source corpus's exposure state; transformation
time is never treated as recording time. When lineage or split-level evidence
is incomplete, the executable manifest requires `unknown`, and the case cannot
be promoted by relabeling or adjudicating it.

The corpus manifest cannot attest to its own cleanliness. The only supported
`independentPromotion` entrypoint loads a reviewed registry under
`YAP_EVAL_CACHE`, verifies it against the separately supplied
`YAP_EVAL_PROMOTION_REGISTRY_SHA256` trust anchor, and hash-checks every private
candidate-lock, freeze, exposure-evidence, participant-authorization, and
reference-review artifact before constructing an internal promotion context.
Every independent case, including contractually excluded material, requires one
case-level transcript-free review receipt rather than copying the same receipt
into each model exposure. The registry authorizes two distinct listeners, an
independent adjudicator, a locale reviewer, and a rights decision owner, and
separately pins the blind assignment, listener, adjudication, locale, rights,
source-identity, attribution, and preprocessing artifacts referenced by the
receipt. The blind assignment must exclude peer reviews and model hypotheses. A
BCP 47 tag with locale subtags requires human exact-locale adjudication; a base
source language marker cannot establish `es-ES`, `en-GB`, `zh-Hans`, or another
specific locale.
That context freezes the exact candidate-lock
SHA-256, model ID/revision, freeze time and freeze-evidence hash, then binds each
exposure decision and evidence URI to the case ID, corpus release/split/item,
raw and decoded audio hashes, reference hash, original recording time, and
evidence hash. Ordinary manifest validation never accepts an independent claim.
Candidate omission, a backdated freeze, invented or changed exclusion evidence,
registry tampering, or any binding mismatch fails closed.
Receipt and registry JSON reject duplicate keys, and bounded artifact identity
is checked on the same opened file handle used for the read. That handle must
remain inside the private cache, including across reparse-point races; portable
artifact paths reject NTFS alternate streams, duplicate review IDs fail before
artifact I/O, and a registry-wide byte budget bounds work. Source URI/retrieval time,
suite/condition labels, audio shape, speaker/timing metadata, reviewed rights,
reidentification policy, known-defect codes, and fractional UTC timestamps must
match the promoted case exactly.
Schema v2 permits only natural source recordings as independent quality cases;
concatenated, looped, perturbed, and generated inputs remain comparator or
runtime evidence. Repeated raw or decoded audio may appear only once per
manifest, preventing the same sample from changing purpose or exposure under a
new case ID. Every case also carries sorted suite membership and controlled
acoustic/use-case labels. Derived cases bind a typed operation, recipe hash, and
ordered source-audio hashes; a transformation cannot validate without its
matching condition label. This makes slice coverage and derivation lineage
machine-auditable without storing reference text or filesystem paths.

No reviewed promotion registry or trust-anchor value is present in this
repository today. The public comparator and runtime paths therefore remain
promotion-ineligible, and loading an independent manifest without the private,
out-of-band-pinned registry fails.
The executable schema prevents duplicate case reviews inside one registry, but
does not invent a cross-registry consumed-case ledger. Selection freshness,
one-time holdout consumption, and retirement after tuning remain external human
evidence that must be pinned before a real promotion.

| Candidate revision | Public source | Exposure decision | Permitted claim |
| --- | --- | --- | --- |
| Nemotron 3.5 ASR v1 | FLEURS, Common Voice, MLS | `known_training` and `known_evaluation` from NVIDIA's model card; exact sample overlap is not disclosed | Comparator/regression only |
| Nemotron 3.5 ASR v1 | Other pre-existing public corpora | `unknown` unless NVIDIA or a corpus owner supplies split-level evidence | Comparator/regression only |
| Cohere Transcribe 03-2026 locked revision | Every pre-existing public corpus | `unknown`; Cohere's disclosed aggregate data description does not identify enough sources | Comparator/regression only |
| Tiron revision `aed145c7d6cc5cbd381a0e87b6d0089bcc76a1fc` | AMI, ICSI, and NOTSOFAR-1 | `known_evaluation`; the publisher reports and may have selected behavior against these corpora | Comparator/regression and upstream reproduction only |
| Any frozen candidate | Sealed Yap Reality Set recorded afterward | `created_after_model_freeze`, provided chain of custody proves the date and no later tuning uses it | Independent promotion holdout until retired |

The first viable public-source contribution to that Reality Set is the
European Parliament's 7-9 July 2026 plenary material. The exact Cohere revision
reports a 10 June 2026 last-modified time and the exact Nemotron revision
reports 6 July 2026 at 13:53:14 UTC. Only source speeches whose published
recording time is strictly later than both values may be considered. The
private registry must bind snapshots of those revision responses, the
Parliament event metadata, and every acquired source artifact; copying these
dates into a manifest cannot self-authorize the claim.

Quality claims require natural human speech. Runtime qualification also uses
deterministic constructed audio because exact durations, sentinel boundaries,
and reproducible overload conditions are necessary to expose system failures.
Neither evidence type substitutes for the other.

### Contamination shortcuts rejected

No public-source heuristic is accepted as proof that a pretrained model did not
see an example. In particular:

- ESB is a multi-domain benchmark assembled from pre-existing corpora, not a
  clean holdout generator. Europarl-ASR and VoxPopuli are explicitly listed in
  NVIDIA's Nemotron training data.
- TED-LIUM, LibriSpeech, AMI, Common Voice, MLS, and other leaderboard corpora
  remain useful comparators, but a newer download or corrected transcript does
  not make the underlying recording unseen. Nemotron explicitly reports
  evaluation on TED-LIUM and training or evaluation on several of these sets.
- A podcast, livestream, audiobook, hearing, or earnings call published after a
  guessed training cutoff is not automatically clean. The exact checkpoint
  freeze must predate the original recording, and audio rights, consent,
  reference quality, acquisition evidence, and later tuning must still pass.
- TTS and digitally transformed audio are reproducible stress inputs, not
  independent natural-speech quality evidence. A generated date does not prove
  acoustic generalization.
- Completing a clipped familiar sentence, correcting an improbable sentence,
  or hallucinating during silence is a serious acoustic-faithfulness failure,
  but no single output proves dataset memorization. Those behaviors can also
  arise from decoder language priors, endpointing, or non-speech handling.

Yap therefore uses public corpora for comparability and regression, and uses a
sealed Reality Set recorded after each exact candidate lineage is frozen for
independent promotion. When the evidence cannot distinguish exposure from
non-exposure, the manifest records `unknown`.

### Acoustic-faithfulness challenge set

The private Reality Set includes natural, post-freeze recordings designed to
separate listening fidelity from plausible-text generation. These are ordinary
quality cases under the same chain of custody, not a self-attested
"contamination detector":

1. incomplete utterances that naturally stop mid-thought and are followed by a
   measured silent tail; no unspoken completion is allowed;
2. grammatical but semantically unlikely sentences, deliberate disfluencies,
   self-corrections, and false starts; the reference is not silently repaired;
3. unpredictable names, nonce words, minimal pairs, serials, mixed letters and
   digits, dates, measurements, negations, and ordered number/unit phrases;
4. paired clean/noisy, close/far, quiet/reduced-speech, and codec-degraded
   recordings whose source wording and critical-token policy are unchanged;
5. speech-free silence/noise/music controls and speech interrupted at live
   endpoint boundaries.

The gate reports raw and normalized insertions, deletions, substitutions,
normalized critical-token retention and order, exact case/punctuation surface
fidelity, false words on zero-reference audio, and unspoken-tail completion
errors separately. A famous public clip truncated
after download may be retained as a regression probe, but cannot support an
independent exposure or promotion claim. Spoken punctuation commands are
scored verbatim at the ASR layer; executing commands or applying formatting is
a separate product behavior and is tested only when that layer exists.

This design follows the NIST AI RMF expectation that test sets, metrics,
representativeness, limitations, and deployment-context evidence be documented,
and uses ISO/IEC 25012's data-quality model as a checklist. It does not claim
formal conformity or regulatory status.

## Candidate public sources

Every adopted source still requires an exact release/revision, file hashes,
license snapshot/hash, attribution, acquisition record, and a source-specific
parser test. Dataset contents remain outside Git.

| Source | Intended Yap coverage | Strengths | Limitations and decision |
| --- | --- | --- | --- |
| [European Parliament 7-9 July 2026 plenary speeches](https://www.europarl.europa.eu/plenary/en/debate-details.html?date=20260706&detailBy=speaker) | Post-freeze natural speech, 24 EU languages, formal spontaneous delivery, speaker transitions, short through long session assembly | Original-language speech audio and revised speech text are published with speaker, start/end, and language metadata. Parliament authorizes commercial and non-commercial reuse of its text and multimedia with source acknowledgement. | **Adopt as an independent-source candidate, not automatic gold.** Never use simultaneous interpretation, whose reuse is expressly restricted. A private acquisition preflight found a 138.987-second download around one published 79-second speech; the exact 30-second pre/post trim isolated the intended source interval. The revised text also differed from literal delivery. Every selected item therefore needs an original-language check, immutable source/trim lineage, two independent listens, adjudication, URL attribution, and a post-freeze registry decision before promotion. This source does not cover every Yap locale, quiet dictation, medical speech, noise, or overlap by itself. |
| [LibriSpeech](https://www.openslr.org/12/) | Clean and harder read English; short regression clips | Established test-clean/test-other splits; 16 kHz; CC BY 4.0 | **Adopt as comparator only.** Read speech, likely benchmark exposure, and not conversational. Never treat it as independent deployment certification. |
| [Google FLEURS](https://huggingface.co/datasets/google/fleurs) | ASR and LID for every locale Yap advertises | 102 languages, parallel prompts, speaker metadata, CC BY 4.0 | **Adopt as comparator only.** It is listed in Nemotron 3.5 training and evaluation, is short read speech, and does not prove meetings, spontaneous speech, noise, or long form. |
| [Mozilla Common Voice scripted and spontaneous speech](https://commonvoice.mozilla.org/en/datasets) | Speaker/accent diversity, short utterances, spontaneous responses, very short and low-energy slices | Community validated; current data is CC0 | **Adopt with access controls as comparator only for Nemotron.** Nemotron lists it in training/evaluation; Cohere exposure is unknown. Exact download terms can prohibit speaker re-identification and re-hosting/re-sharing. Use only from a private external cache after recording the exact release terms. |
| [Multilingual LibriSpeech](https://www.openslr.org/94/) | Eight-language read-speech regression | Established multilingual corpus, CC BY 4.0 | **Adopt as comparator only.** Nemotron lists MLS in training and evaluation; it is neither spontaneous nor an independent release gate. |
| [AMI Meeting Corpus](https://groups.inf.ed.ac.uk/ami/corpus/) | Multi-part four-person meetings, close-talk versus far-field, overlap, disfluency, mostly non-native English | 100 hours, synchronized channels, manual speaker transcripts, CC BY 4.0 | **One official evaluation meeting segment is now pinned as a comparator.** The corpus documents known transcript/data problems; retain the upstream defect caveat and require Yap adjudication before any quality threshold or promotion claim. Tiron publishes AMI results, so AMI is comparator-only for that route. |
| [ICSI Meeting Corpus](https://groups.inf.ed.ac.uk/ami/icsi/) | Natural technical meetings, long sessions, mixed versus close channels, spontaneous/reduced speech | About 70 hours with orthographic transcripts and speech-quality annotations, CC BY 4.0 | Older recording domain and formats; speaker/timing parser must be verified. Adopt a stratified official subset. Tiron publishes ICSI results, so it cannot independently promote that route. |
| [NOTSOFAR-1](https://github.com/microsoft/NOTSOFAR1-CHALLENGE) | Real far-field office meetings, 4-8 attendees, commercial devices, room/acoustic diversity, speaker-attributed scoring | Exact ground-truth evaluation subsets, real and simulated data, CC BY 4.0 | Use only the current open-research subsets. Exclude challenge-only Dev-set-2 and documented faulty Rockfall device data; record the exact release because annotations are still being upgraded. Tiron publishes NOTSOFAR-1 results, so this is comparator-only for that route. |
| [LibriCSS](https://github.com/chenzhuo1011/libri_css) | Controlled overlap, continuous input, far-field replay, chunk/order stress | Potentially useful constructed meeting-like engineering stress | **Hold.** The repository's MIT text covers software and notes original LibriSpeech's CC BY 4.0 license, but does not expressly license the separately distributed new distant-microphone recordings. Do not ingest until the downloaded archive or authors establish the data rights. |
| [PriMock57](https://github.com/babylonhealth/primock57) | Medical terminology, clinician-patient turns, accents, disfluency, diarized long conversations | 57 simulated consultations/8h38m, manual utterance transcripts, separate channels, CC BY 4.0 | Mock UK primary care, not patients, device specialists, Medtronic vocabulary, or clinical validation. Adopt as public domain-specific regression only. |
| [Corti Med-Dictate](https://huggingface.co/datasets/corti/med-dictate) | Medical dictation, spoken formatting, terminology, numbers, and 107-450-second English/German/French recordings | Forty evaluation-only recordings totaling about 1h54m, made with contributor consent; the dataset card states that it contains no real patient data or PHI and supplies raw/formatted references plus medical-term lists. | **Adopt as a medical comparator only.** It predates the exact Nemotron freeze, is not a clinical or Medtronic holdout, prohibits training/fine-tuning and clinical use, and has contributor-withdrawal obligations. Snapshot the complete Corti license/addendum and keep the corpus private; do not redistribute it through Yap artifacts. |
| [MUSCAT multilingual scientific conversations](https://huggingface.co/datasets/goodpiku/muscat-eval) | Bilingual multi-speaker scientific discussion, code switching, device/channel variation, segmentation, and diarization across `en-de`, `en-zh`, `en-tr`, and `en-vi` | Natural bilingual discussions, manual-segment references, full-session transcripts, and Meeting Owl/Aria/Raspberry Pi recordings directly exercise several missing slices. | **Hold pending an explicit data license and recording-time evidence.** The current repository exposes about 3.45 GB of audio and references but no license file or license metadata. It cannot enter even the private comparator cache until reuse rights are established; its pre-freeze publication also cannot prove independent Nemotron generalization. |
| [OpenSLR RIRS_NOISES](https://www.openslr.org/28/) | Deterministic noise, reverb, distance, and SNR transformations of already-labeled speech | Useful composite of simulated and third-party room/noise sources | **Hold the composite.** OpenSLR labels SLR28 Apache 2.0, but it includes RWCP material whose owner limits use and redistribution. Inventory every subtree; exclude RWCP-derived data absent permission and admit only independently verified components. |
| [Earnings-21/22](https://github.com/revdotcom/speech-datasets) | Natural long-form, accents, names, entities, numbers | Long, entity-dense calls and versioned reference corrections | **Hold audio for counsel review.** The repository's CC BY-SA license files expressly cover transcripts and associated alignment text, not the downloaded call audio. Fair-use rationale is not an enterprise audio license. Do not rehost, commit, or place audio in CI. |
| [wSPIRE](https://spiredatasets.ee.iisc.ac.in/wspirecorpus) | Paired neutral/whispered speech across devices | Current portal reports about 36 hours, five devices, and CC BY 4.0 | **Adopt only after exact archive/version verification.** Portal versions disagree on speaker count. Scripted studio whisper is a low-vocal-effort proxy, not real mumbling, spontaneous dictation, or noise coverage. |

### European Parliament private intake diagnostic

The source-specific parser found 1,193 usable monolingual speech/reference pairs
across 24 languages and excluded unavailable placeholders, zero-duration
records, malformed links, and multilingual `XM` blocks. A deterministic private
post-freeze screen selected one speech in each of 19 languages. Every downloaded
audio asset decoded to its published speech duration plus an approximately
60-second media envelope; exact leading/trailing removal produced 16-kHz mono
PCM tracks at the published durations. The bounded DOCX parser extracted the
official revised text without treating it as literal gold. Source, derived,
reference, and client-preprocessing locks remain private and hash-bound.

The desktop production Silero path processed all 19 tracks. Natural continuous
speech exposed Sherpa result-buffer growth under the former 30-second allocation;
a 120-second result ring removed the warning while preserving the exact
preprocessing-evidence hash. On GB10, a c8 Cohere/vLLM screen completed nine
supported locales/711 seconds in 6,919 ms model-ready wall time. A c8 native
NeMo screen completed 18 supported locales/1,380 seconds in 9,024 ms after a Yap
fixed-route metadata defect was corrected; its scheduler formed a true batch of
eight and returned no failed or busy request. The provider aggregates were
15.86% and 22.06% normalized WER respectively, but they cover different locale
sets and the references are revised/unreviewed. They are therefore descriptive
intake diagnostics, not a provider ranking, locale promotion, or independent
quality gate. Audio, references, transcripts, case identities, and raw evidence
stay outside Git; two independent listens, adjudication, attribution, and the
frozen registry decision remain mandatory.

### First immutable public comparator: FLEURS `es-419`

The first admitted public source is the FLEURS `es_419` test split at immutable
dataset revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`. The public lock
freezes the 582,112,372-byte audio archive at SHA-256
`981802f6c828fd214fcf8bfc1036d80c9184b6eeb5650b3f7882f8affec046c9`,
the 599,882-byte TSV at SHA-256
`d107a93a4f54a18ac25cd470bb4cdadce14fb075b0c1d1542258e274d209ec09`
and Git blob `cdec7d5980706c7f354b89a4a4d31949b65c100f`, plus the exact
CC BY 4.0 legal-code digest. The source bytes remain under the external private
`YAP_EVAL_CACHE`; they are not repository or hosted-CI artifacts.

The source-specific Python 3.12 parser and focused synthetic contract tests
distinguish reusable prompt IDs from unique audio filenames, reject links,
traversal, changed membership, hashes, row shapes, and WAV metadata, and emit no
transcript text or path. The parser inspected all 908 real float32 WAV cases:
178,017,600 samples (3 h 5 min 26.1 s), from 78,720 to 484,800 samples (4.92 to
30.30 seconds), with an exact archive/metadata match. Seventeen focused source,
comparator, and evaluation-runtime tests also cover canonical PCM conversion,
shallow installed-source mounts, real-repository exclusion, immutable result
publication, batch shape, privacy, runtime identity, and the scoring overlay.

Locale and provider routing remain separate. FLEURS config `es_419` is
canonical evaluation locale `es-419`; it is not `es-US` or `es-ES`. Cohere's
internal fixed-language prompt is the provider code `es`. This comparator may
measure that route, but Cohere's exposure to pre-existing public corpora is
unknown, so it cannot promote any Spanish product locale by itself. A later
catalog entry still needs a frozen, locale-matched natural Reality Set and the
predeclared quality/runtime gate.

The locked Cohere route executed privately on GB10 on 2026-07-21 using Python
3.12.3, NVIDIA PyTorch `26.06-py3`, Torch
`2.13.0a0+8145d630e8.nv26.06`, CUDA 13.3, BF16, and batch size eight. The
20-case screen measured 0.4525% normalized word error rate and 51.63 audio
seconds per wall second. The frozen all-case run completed all 908 cases and
11,126.1 seconds of audio in 61.455 measured seconds: 3.5549% normalized word
error rate, 1.7230% normalized grapheme error rate, 4.6110% raw word error rate,
0.8068 punctuation F1, and 181.04 audio seconds per wall second. It used 113
full batches of eight plus one batch of four.

Inference ran without network access as an unprivileged process with a read-only
root, dropped capabilities, read-only source/model/corpus mounts, and a private
result mount. General temporary storage remained non-executable; only a
disposable size-bounded PyTorch compiler cache was executable. Per-case references and
hypotheses remain in private owner-restricted evidence on the DGX and Windows
evaluation caches; only this transcript-free aggregate is recorded here. The
run is a descriptive Cohere regression baseline. It does not establish clean
model exposure, locale promotion, spontaneous/noisy/meeting quality, long-form
correctness, Cohere vLLM parity, concurrency capacity, or a production SLO.

### First immutable long-meeting comparator: AMI `ES2004a`

The public `ami-meeting-comparator.lock.json` freezes AMI annotation release
1.6.2 and meeting `ES2004a`, which appears in the official unseen-scenario and
full-corpus ASR evaluation sets. It binds the 22,887,865-byte annotation ZIP,
both 33,579,394-byte PCM16/16-kHz mono recordings, the four exact speaker-word
XML members, CC BY 4.0 provenance, and the close-headset-mix and distant
Array1-channel-1 conditions. The recordings each contain 16,789,675 samples
(1,049.3546875 seconds). Raw audio and annotation text remain exclusively in
the owner-private external `YAP_EVAL_CACHE`.

The Python 3.12 boundary rejects path escape, normalized or case-insensitive
duplicate members, links/devices, encryption, unsupported compression, unsafe
expansion ratios, changed hashes/sizes/counts, active XML declarations,
non-sample-aligned or non-monotonic timing, duplicate source IDs, and a changed
PCM shape. It preserves the four speaker timelines and labels its deterministic
start/end/agent/source ordering as a scoring policy rather than a unique true
ordering for overlap. Aggregate inspection of the real ARM-private artifacts
found 3,135 word elements, 60 vocal sounds, 57 disfluency markers, six gaps,
and 764 word elements involved in positive cross-speaker overlap. Focused ARM
implementation inspections completed in under one second with under 128 MiB
peak RSS and emitted no transcript text, audio, or private path.

At exact executable commit
`2caf1969000154ffba24511a5c35b57f7f975036`, the desktop's production imported-
audio normalizer and pinned Silero model processed both complete recordings.
The close mix retained 151 speech intervals and 736.861 speech seconds; the
far-field channel retained 130 intervals and 620.361 speech seconds. Each
16,789,675-sample source became a 16,789,680-sample canonical PCM stream with
five declared alignment-padding samples and no modified source sample. The
server's production `BatchInputPreparation` then reverified every 30-second
client chunk and the normalized PCM hash before creating 37 contiguous
utterance windows per condition. Close mix used 25 VAD-silence and 11 hard
30-second boundaries; far field used 32 VAD-silence and four hard boundaries.
Both plans ended once at end-of-input and preserved every canonical sample.

The same prepared inputs then ran through exact-head images
`sha256:4076085166bfc002a0d40c8e01a2a72ab0bcaadbd940ec4d65ab9bb9fbb3dc04`
for Cohere/vLLM and
`sha256:4bf0e605eb14722555d0aa9724798b9f68ce236ad70a7c20500d92698d43c43e`
for native NeMo/Nemotron. The executable AMI reference renderer retained all
3,135 ordered XML word elements, including 521 punctuation elements, and the
pinned transcript scorer reduced that to 2,653 normalized word units per
condition. Results were:

| Provider and condition | Model-ready wall | Normalized WER | Insertions / deletions / substitutions | Punctuation F1 |
| --- | ---: | ---: | ---: | ---: |
| Cohere/vLLM, close mix | 8.615 s | 46.250% | 403 / 746 / 78 | 25.496% |
| Cohere/vLLM, far field | 4.473 s | 42.367% | 76 / 886 / 162 | 29.021% |
| NeMo/Nemotron, close mix | 18.065 s | 26.046% | 10 / 568 / 113 | 11.621% |
| NeMo/Nemotron, far field | 16.858 s | 37.919% | 11 / 777 / 218 | 10.191% |

Across the two conditions, Cohere/vLLM measured 44.308% normalized WER and
38.591% normalized grapheme error, while NeMo/Nemotron measured 31.983% and
24.952%. NeMo/Nemotron was materially better on lexical accuracy for this one
meeting; Cohere/vLLM was faster and produced the higher punctuation F1. This
refutes a universal "Cohere is the accuracy route" assumption but does not
promote Nemotron or establish a general provider ranking.

The private vLLM and NeMo receipts are bound by SHA-256
`7ebc4dce83fc4e750b5024b2bf70806f6b93624a4e63827b6d3d793a0f52cae8` and
`bdb5fefc618265d82101120c50e84a7c830c7ebaa4d50bfa774aa399a55a02b4`;
the transcript-free score evidence is
`bc2428bd2f56a29d44156c508f9825a7590874c55fa564ab016c48b20b7041c1`.
References, hypotheses, paths, and per-case provider results remain private.
Both containers and both listeners were absent afterward.

This is descriptive long-meeting evidence, not a quality gate. AMI describes
the references as manual transcription supplemented by forced alignment and
publishes known data problems, so they are not asserted to be infallible ground
truth. Exposure remains `unknown`, the comparator is promotion-ineligible, and
the unreviewed deterministic flat reference cannot set a Phase 6 threshold.
Neither provider returned timestamps or speaker identities in this run;
overlap-specific WER, speaker-attributed metrics, source-time drift, and time-
quartile completeness therefore remain unavailable rather than inferred.
Independent reference review and the frozen representative gate remain open.

Under [ADR 0027](../adr/0027-tiron-joint-speaker-attributed-meeting-transcription.md),
this exact AMI source becomes one public Phase 8 Tiron reproduction input, not
the messy-meeting promotion holdout. Phase 8 must add compatible speaker-aware
references/scoring without treating the flat deterministic overlap ordering
above as unique truth. ICSI and NOTSOFAR-1 join the public comparator class;
the independent acceptance suite remains separately sealed and adjudicated.

### Sources not in the enterprise baseline

- Earnings-21/22 transcripts have explicit CC BY-SA terms, but those files do
  not grant rights to the call audio. Both remain legal holds for audio use even
  though Earnings-22 would otherwise supply valuable natural recordings beyond
  two hours. Exact-duration runtime tracks do not depend on that corpus.
- VoxPopuli is CC BY-NC; Buckeye is free only for non-commercial use; CORAA is
  CC BY-NC-ND. They must not enter Yap's enterprise qualification baseline.
- Switchboard and several accessibility corpora require an LDC agreement, data
  use agreement, or organizational approval. They are procurement/governance
  options, not developer-owned dependencies.
- The Speech Accessibility Project is valuable for atypical speech, but access
  requires an approved proposal and data use agreement. That is an explicit
  governance handoff.

## Corpus manifest and reference controls

Redistributable comparator manifests may be committed to Git when their metadata
and hashes reveal no private case identity. Independent-promotion manifests,
references, hypotheses, inference-result/runtime locks, scorer locks,
critical-token policies, terminology-context request identities, and case
evidence remain under the private external `YAP_EVAL_CACHE`; only redacted
aggregates may leave that boundary. Each case
records at least:

- corpus ID, exact release/revision, upstream split/item and source URI;
- audio SHA-256, byte size, decoded PCM SHA-256, duration, channels, sample
  rate, codec, and acquisition timestamp;
- reference SHA-256, reference tier/revision, language/locale, explicit primary
  and punctuation scoring profiles, optional private critical-token-set SHA-256,
  speaker count, timing/speaker annotation availability, and adjudication state;
- acoustic and speech labels such as close/far, clean/noisy, overlap,
  spontaneous/read, accent region when supplied, and synthetic transformation;
- license identity, license-text SHA-256, attribution, restrictions, and whether
  redistribution, identity inference, or commercial use is forbidden;
- known source defects, excluded intervals/devices, and contamination risk;
- exact candidate model ID/revision, candidate-lock hash, verified freeze time,
  and freeze-evidence hash;
- per-model ID/revision exposure state and evidence source. Unknown exposure is
  never silently upgraded to clean, and a public test split is not sufficient
  evidence of exclusion from pretraining;
- intended suite (`smoke`, `asr-runtime-promotion`, `extended`, or future
  `approved-private`) and the exact metrics for which the case is valid.

Acquisition fails closed on an unknown revision, hash, license, transcript
schema, duration, or channel layout. `YAP_EVAL_CACHE` points to a private
external directory; it may never default inside the repository. GB10 material
uses private permissions and a networkless invocation after acquisition.
Hosted CI sees only tiny licensed/synthetic contract fixtures. Raw audio,
references, hypotheses, paths, and per-utterance errors never enter PR logs or
public artifacts.

`yap_server.evaluation.corpus_manifest` enforces the model-revision exposure
classification and prevents unknown/exposed cases from being labeled as
independent promotion evidence. Independent claims additionally require
`load_promotion_corpus_manifest`, a private registry, its out-of-band SHA-256,
verified candidate-lock/freeze/exposure artifacts, and one independently pinned
human-reference review per promotion case; values copied from the manifest are
not a trust source. The review registry authorizes participant roles and binds
separate blind-assignment, listener, adjudication, exact-locale, rights-owner,
source-identity, attribution, and preprocessing receipts. The loader compares
the complete candidate set and case-bound exposure evidence, admits only natural
source audio, rejects repeated raw or decoded audio, and requires source
release/split/item identity, hashes, duration/format, reference tier and
adjudication, exact reviewed rights and known defects, and a later original
recording timestamp for a post-freeze claim.
The registry also binds the exact scorer-lock digest and a canonical per-case
evaluation-policy digest covering language, primary profile, punctuation
profile, and critical-token policy identity. `score_manifest_case` is the only
promotion adapter: it same-read hashes the private manifest, verifies the
reference and executing scorer lock, and derives duration and decoded identity
from the hash-verified PCM WAV instead of trusting manifest duration fields. It
also requires an out-of-band-digest-pinned inference-result lock binding the
  case, raw and decoded audio, hypothesis hash, candidate lock, exact model
  revision, a hash-verified runtime lock, and whether provider-native
  terminology context was unused or supplied. When supplied, the lock binds the
  source policy and exact provider request by SHA-256 plus bounded entry/byte
  counts; it emits no term text or artifact path. It applies the manifest policy
  and emits the case, manifest, evaluation-policy, scorer-lock, candidate-lock,
  inference-result-lock, model, runtime, and terminology-context identities
  without emitting text or paths.
It intentionally does not ship a placeholder corpus manifest: the first real
manifest is created only after exact candidate locks, corpus releases, rights
decisions, reviewed trust evidence, and hashes exist.

The benchmark's locked public LibriSpeech clip is explicitly labeled an
exposure-`unknown` regression comparator and is ineligible for independent
promotion. `yap_server.evaluation.duration_tracks` separately builds immutable,
exact-sample runtime controls under `YAP_EVAL_CACHE`, hashes raw and decoded
audio, records source-to-output segment mappings without paths or transcript
text, and fixes `accuracySampleIncrement` to zero. A runtime adapter accepts a
runtime track only when every source is covered by the locked fixture
provenance, suppresses WER, and emits `independentPromotionEligible: false`.

The executable packet preserves upstream and final reference hashes, two
independent listener results, and an adjudicated result; any changed listener
decision or reference hash requires explicit reason codes. It includes an
evaluation-policy digest, participant roles, human exact-locale basis, rights
decision owner, known-defect codes, and artifact hashes without placing
transcript text or paths in Git; the registry separately pins the scorer
implementation lock. A versioned contract for word/non-speech/overlap/speaker/
inaudible/source-time annotations and allowed transcript alternatives remains
open workflow/evidence work and is not accepted by the current scorer. Domain
experts must separately review medical/device entities and units before those
claims can pass. Adjudication improves label quality but does not cure model
exposure; those are separate manifest decisions.

## Coverage matrix

The promotion subset must cover each row with multiple speakers where the
source permits. One recording may satisfy several rows, but an aggregate score
cannot conceal a failing row.

| Use condition | Primary evidence | Required assertions |
| --- | --- | --- |
| Clean close-talk dictation | LibriSpeech, FLEURS, Common Voice | Verbatim and normalized WER/CER, punctuation, exact duration and language |
| Low-volume, reduced, hesitant, false starts, filler-heavy speech | Common Voice spontaneous, AMI/ICSI excerpts, approved Yap gold | Short-utterance deletion rate, final WER, no early endpoint truncation; gain reduction alone is not articulation coverage |
| Natural long single-speaker speech | ICSI/AMI single-speaker spans; cleared Earnings-21 candidate | No skipped, duplicated, reordered, or cross-chunk words; entity/number preservation |
| Close and far multi-speaker meetings | AMI, ICSI, NOTSOFAR-1 | WER plus speaker-attributed meeting metrics; channel/source-time identity retained |
| Simultaneous/overlapping speech | LibriCSS, NOTSOFAR-1, AMI overlap regions | ORC/cp/tcpWER as applicable; overlap slice reported separately |
| Participant and window-speaker scale | Independent messy-meeting holdout plus licensed constructed controls | More-than-15-person session linking; late arrivals and returns; one through eight distinct Tiron window slots; explicit typed degradation when more than eight talkers occur within 30 seconds |
| Medical conversation and terminology | PriMock57 plus future approved use-context holdout | General WER plus medical entity, negation, number, dose/unit, and speaker-turn error rates |
| Every advertised locale | FLEURS plus exact-locale Common Voice where available | Per-locale WER/CER and language tag accuracy; no macro average may promote a failed locale |
| Related/unsupported language and code switch | FLEURS/Common Voice controls plus licensed natural and explicit constructed switch boundaries | Correct unknown/manual-review behavior; per-span language accuracy, source-time switch-boundary error, false-switch rate, and no duplicated/dropped transcript text gate the Phase 6 intra-utterance claim |
| Noise, reverb, distance, echo, clipping, AGC, narrowband and codec loss | RIRS_NOISES transformations plus natural far-field corpora | Paired clean/degraded delta at fixed seeds and SNR; source reference unchanged |
| Silence, music, background talk, cough/laugh and non-speech | Licensed negative audio and generated silence | False words/minute, false language tags, no invented confidence, bounded empty result |
| Virtual-meeting transport | Public labeled speech passed through fixed Opus/sample-rate/channel/jitter/drop simulations | No timeline drift, loss concealment is explicit, source gaps preserved, output remains bounded |
| Names, acronyms, numbers, dates, measurements and device vocabulary | Adjudicated public/entity fixtures plus approved domain prompts | Entity WER, normalized critical-token retention/order, exact case/acronym/number/unit surface fidelity, and punctuation separately; semantic number/unit equivalence remains a distinct unimplemented gate |
| Interrupted, low-predictability and counterfactual dictation | Sealed post-freeze Reality Set plus comparator-only clipped transforms | No unspoken continuation, no silent semantic repair, raw/normalized edit counts and ordered critical-token fidelity reported separately |
| Restart, retry and cancellation | Deterministic sentinel fixtures | One immutable job/result, no duplicate work or publication, acknowledged cancellation, immediate recovery |

Fairness reporting is descriptive and slice-based: locale, accent information
provided by the corpus, speaker, microphone condition, duration, speech style,
and noise condition. Yap does not infer protected or demographic attributes
from voices. Sparse slices are reported as insufficient evidence rather than
combined away.

## Duration and workload qualification

The runtime ladder is deliberately orthogonal to the natural-quality corpus.
Constructed long tracks concatenate varied licensed utterances with unique
spoken/reference sentinels and a segment manifest. Repeating one sentence is
insufficient because it can hide chunk duplication, omission, or reordering.
The machine-validated [runtime plan](../../server/asr-evaluation-plan.json)
encodes the exact sample counts, executable/deferred systems, load cells,
admission limits, provider-specific execution boundaries, result-envelope
bound, and predeclared GB10 resource profiles.
It contains no audio paths or reference text. The initial exact-duration
generator can truncate, concatenate, or loop locked PCM16 sources. A looped
single-clip track is valid only for duration, lifecycle, load, and resource
behavior; it cannot establish long-form transcript quality, sentinel order, or
independent generalization.

For the desktop row, deterministic replay begins at the prepared-audio-frame
boundary. The runner streams ten-millisecond frames through the production
bounded local-ASR adapter, one live worker, and finalization; it does not load a
multi-hour WAV into memory. The checked-head SHA, public-plan hash, private
suite, per-track manifests, raw WAV, and decoded PCM are independently bound,
while evidence retains only aggregate timing/counts and whether text appeared.
That run is duration/lifecycle evidence. Physical microphone-to-final timing,
rendered UI responsiveness, and natural short-utterance accuracy remain
separate target-device and quality gates.

The executable private-suite builder derives the exact ordered case set from
the validated plan and atomically publishes all tracks with a hash-bound
`suite.json` under external `YAP_EVAL_CACHE/runtime-tracks`. It accepts repeated
vetted PCM16 source WAVs, decodes and hashes them once for the collection, and
rechecks raw identity before publication. Per-case
`expectText` is explicit and hash-bound, but a non-empty result is not a WER or
long-form quality claim. The source license/provenance register, natural
references, and any sentinel transcript stay outside this runtime-control
manifest and remain independently governed by the private corpus contract.

| Mode | Durations | Required workload |
| --- | --- | --- |
| Live utterance/endpoint | 0.25, 0.5, 0.75, 1, 1.12, 2, 5, 10, and 30 seconds | Clean, low-energy, noise-only, speech after leading silence, trailing silence, interrupted speech. For sub-chunk corrections, report shortcut-release-to-final-text latency, blank-result rate, leading/trailing phoneme clipping, and raw transcript accuracy separately. |
| Continuous local-live replay | 30 seconds; 5, 15, 30, 60, and 120 minutes | Nemotron at real-time pacing with natural pauses, one 15-minute noisy/far-field track, time-quartile quality, backlog/memory slope, and cancellation/restart points. If two-hour live cannot pass, lower the advertised live-session bound. |
| Batch | 30 seconds; 2, 5, 15, 30, 60, and 120 minutes | Natural quality cases where available plus deterministic sentinel tracks at every exact duration |
| Maximum boundary | exact current four-hour ceiling and one-sample-over | One c1 exact-ceiling runtime if four hours remains supported; deterministic rejection before inference above the ceiling. Otherwise lower the supported ceiling to the longest qualified duration. |
| Homogeneous concurrency | c1, c2, c4, c8 on 30-second inputs; c2 on 15-minute inputs | At least 200 short completions per level before descriptive p99, two long waves, cold/warm separation, exact identity, and server batch/queue statistics |
| Mixed concurrency | c8 with four 30-second, two 15-minute, and two 30-minute requests, plus separate route/cancellation variants | No cross-request audio/result leak, starvation, head-of-line deadlock, or unbounded queue growth; provider-owned internal batching remains isolated |
| Long-load interaction | two 120-minute reservations plus a one-second request; c2 15-minute | Exact aggregate-PCM rejection/retry, short-work bound, and long-work progress |

This is not a full Cartesian product. Phase 6 uses pairwise, risk-weighted
coverage:

1. every duration runs on one deterministic identity-rich track;
2. every natural quality slice runs at its native duration;
3. acoustic transformations run on representative 30-second and 15-minute
   references at fixed SNR/severity levels;
4. c2/c4/c8 runs focus on the 30-second tail sample, c2 15-minute waves, and
   one mixed c8 long workload; and
5. only the exact maximum and two-hour cases run at c1 unless evidence exposes a
   scaling defect.

The executable systems remain distinct: local-live sherpa-onnx Nemotron;
Transformers Cohere/Nemotron references; the Cohere vLLM candidate; and the
resident NeMo finalized-utterance candidate. Client-facing server live remains
future work. The NeMo candidate's executable internal finalized boundary is not
a `/v1/live`, WSS, or authenticated multi-owner claim. Phase 6
can prove one desktop-live session plus concurrent development-owner batch
requests. `/v1/live` and authenticated owners do not execute yet, so batch load
must not be presented as server-live, authenticated-user fairness, or production
capacity. Those remain later gates.

The standard resident-provider runner executes only ordinary complete and
complete-source load cells. It requires track audio and results under the
private external cache and emits explicit expectation decisions. Cancellation,
fixed/automatic parity, and admission cells deliberately fail closed at this
entry point until specialized runners observe their exact named behavior; a
generic wave and a satisfied minimum-completion count are not sufficient proof.
The fixed/automatic NeMo cell requires identical case-folded lexical tokens and
complete source-span/language-contract parity while retaining exact rendered
text parity as a separate diagnostic. This avoids misclassifying deterministic
prompt-dependent casing or punctuation as different recognized words.

The ordinary exact-track runner also groups completed results by audio duration.
Every repeated immutable input must retain one non-empty lexical identity;
exact rendered identity count remains visible as a separate aggregate. A
focused 200-request Cohere/vLLM repetition produced 189 copies of one rendering
and 11 of a second, with all 92 lexical tokens identical and the difference
limited to four commas. Neither disabling the V1 engine subprocess nor enabling
the pinned runtime's batch-invariant CUDA mode eliminated the rendering split.
This is not ignored: representative accuracy continues to score punctuation,
while runtime stability fails on word drift rather than a near-tied punctuation
rendering.

Synchronized Cohere c1/c2/c4/c8 controls must retain one authoritative result
identity per request while vLLM owns continuous batching internally. Mixed-
duration c8 work measures queue delay, short-request head-of-line latency,
throughput, bounded progress, and result isolation; Yap never concatenates or
pads one request into another. The cancellation probe dispatches a long leader,
confirms a distinct follower has entered the request path, closes that
follower's active HTTP connection, requires bounded acknowledgement, and then
runs a distinct recovery request. Successful recovery does not prove backend/
GPU preemption, process teardown, GPU-context teardown, or container teardown.
Nemotron NeMo repeats equivalent properties with additional streaming/cache-
state assertions in its own gate.

### Retired Triton runtime evidence

The following focused measurements explain why the common Triton plane was
rejected. They remain private/historical and do not define the current runtime
matrix or promotion target.

Focused non-gate evidence on 2026-07-17 ran an immutable 480,000-sample
(30.000-second) looped runtime control through the development GB10 Triton
candidate at c1. One request completed in 547 ms wall time; Triton reported
439.517 ms inference and 2.164 ms queue time. The evidence reported
`maximumWordErrorRate: null`, `accuracySampleIncrement: 0`, and
`independentPromotionEligible: false`. This proves the exact-duration runtime
seam, not quality, concurrency, steady-state capacity, or checked-head
promotion. Raw results stayed in the private external cache and the temporary
SSH tunnel was closed after the run.

A later focused scheduler comparison used a corrected synchronized-wave
release-to-result harness with 200 exact 30-second runtime controls per slice.
The 2-ms versus 10-ms results were respectively 58.796 versus 57.692
audio-seconds/second at c1 and 162.092 versus 164.240 at c8. Their c1 p95 values
were 531/532 ms and c8 p95 values were 1,640/1,594 ms. The 10-ms challenger
therefore produced only a 1.3% c8 throughput change while regressing c1
throughput by 1.9%; it was rejected as non-material and the 2-ms policy was
restored. These measurements are development evidence rather than a frozen
capacity gate, and the private per-request results remain outside Git.

Adversarial review invalidated both early exploratory cancellation files because
the old timer could fire before confirmed dispatch and its acknowledgement value
was derived from the configured delay rather than the actual intent timestamp.
The corrected transport state machine also makes an already completed normal
result win over later cancellation intent and rejects contradictory or polluted
server counters. The old 2-ms and 10-ms results therefore prove neither
acknowledgement nor sibling isolation.

A first corrected private 2-ms development rerun confirmed both dispatches,
measured 31 ms from actual intent to acknowledgement, and matched two successful
singleton inferences plus one failed pre-inference cancellation. The sibling
and recovery completed in 297/94 ms, so it proved bounded cancellation/recovery
rather than same-batch isolation. An uncontrolled eight-request follow-up put
seven siblings in a batch of seven but inferred the cancelled request as the
remaining singleton; the claim correctly stayed false.

The post-preparation release control then produced two complementary results. At
100 ms, cancellation occurred before inference: the leader was singleton, six
siblings formed a batch of six, recovery was singleton, and the isolated delta
was eight inferences with one server failure. At 500 ms, the leader was
singleton, six siblings returned from a batch of seven, and recovery was
singleton. Isolated counters reported nine inferences, three executions, nine
successes, zero failures, and `{1: 2, 7: 1}` batch executions. The one absent
batch-of-seven response therefore identifies the cancelled member. All six
same-batch siblings completed; client cancellation acknowledgement was 47 ms
and recovery was 78 ms. Server success for the cancelled member means the run
proves client cancellation isolation and service recovery, not termination of
backend or GPU work. It remains private dirty-development evidence; the frozen
Phase 6 candidate must rerun it.

An initial corrected duration-edge rerun produced five singleton executions. A
post-tensor two-request rerun also remained singleton and correctly stayed
inconclusive. The controlled c8 replacement then produced one short singleton
leader and one batch of seven containing all three short and four long followers.
The boundary pair remained two singleton executions. Same-bucket per-wave
counters were `{1: 1, 7: 1}`, boundary counters were `{1: 2}`, and total counters
were eleven inferences, five executions, and `{1: 4, 7: 1}`. This proves the
power-of-two scheduler boundary on the dirty 2-ms candidate. The short control
rose from 297 ms solo to 1,500 ms in the mixed wave, a 1,203-ms head-of-line
penalty. The result is descriptive offline-batch evidence, not a latency SLO or
proof that power-of-two buckets are optimal. It was the requirement for that
rejected batching profile and is superseded below.

That scheduler-specific requirement is superseded for the current candidate by
runtime-plan schema 3. The July 21 `single-resident-queued-v1` successor fixes
model execution at batch size one. Focused exact-reference probes passed for
Cohere fixed, Nemotron fixed, and Nemotron dynamic routes; synchronized c4 runs
over eight identical 7.4-second inputs retained one authoritative output and
reported only singleton executions. Warm Cohere measured 329/661 ms p50/p95;
Nemotron fixed measured 209/415 ms; Nemotron dynamic measured 220/432 ms. These
remain direct-worker dirty-source controls rather than end-to-end or frozen SLO
evidence. A distinct queue probe cancelled a dispatched follower before model
execution, acknowledged it in 20 ms, retained its leader, and completed a
singleton recovery in 132 ms. The earlier power-of-two/batch-of-seven evidence
remains negative and historical; it is not a gate requirement for the corrected
profile.

## Metrics and fail-closed promotion rules

### Transcript and language quality

- Preserve both verbatim WER/CER and a pinned, language-specific normalized
  score. Never overwrite the reference or report only the more favorable one.
- Report insertion, deletion, and substitution counts, punctuation precision/
  recall/F1, and per-locale language-tag confusion.
- Report entity/critical-token retention, order, and exact-surface fidelity
  separately for names, acronyms, negation, numbers, dates, measurements,
  medication/device terms, and units. Ordinary WER gives a filler and a
  safety-relevant token the same weight.
- For long form, report chunk-boundary WER, sentinel omission/duplication/order,
  transcript completeness, and source-time drift.
- For meetings, use the pinned NIST SCTK/MeetEval-compatible scorer appropriate
  to what actually executes: SISO WER for Phase 6's flat text, and tcORC-WER
  only when timestamped speaker-agnostic multi-stream output exists. Phase 8
  adds tcpWER/cpWER, speaker-attributed WER, DER/JER where compatible,
  overlap-region word deletion/recall, overlap/collar policy, speaker-count and
  window-capacity error, speaker merge/split/fragmentation, and per-speaker
  macro reporting. Forced-aligned source timings are derived, not timestamp
  gold.
- The canonical Phase 6 promotion scorer is
  `yap_server.evaluation.transcript_scoring`, installed through the pinned
  `evaluation` extra. It reports raw NFC and normalized
  NFKC/casefold/NFKC word and extended-grapheme edit counts, dependency/Unicode
  versions, scorer-source and normalizer revisions without emitting transcript
  or token text. Private case evidence retains input identities only inside
  `YAP_EVAL_CACHE`; public evidence is redacted and aggregate. Each manifest
  case freezes an explicit
  `word-primary-v1`, `grapheme-primary-v1`, or `silence-false-words-v1` profile;
  the scorer never guesses the metric from a language label. Mixed-language
  `mul` cases require grapheme-primary scoring. All profiles still report both
  word and extended-grapheme counts for diagnosis. The manifest also freezes
  `unicode-word-boundary-v1` punctuation scoring. Its micro aggregate sums
  reference, hypothesis, and correct mark counts before deriving precision,
  recall, and F1.
- Safety-relevant vocabulary is an optional private policy, never a hard-coded
  medical word list. The scorer requires the policy and its surface-bound
  SHA-256 together. It uses deterministic NFKC/casefold normalization for
  semantic retention and order, plus a separate NFC case- and punctuation-
  sensitive match against the policy's exact written form. Both paths use
  boundary-aware longest matching while permitting no-space-script matches and
  preserve meaningful internal forms such as decimals, unit slashes, hyphens,
  and alphanumeric device terms. Private evidence contains the policy hash,
  normalized occurrence precision/recall/F1, ordered-sequence edit score, and
  exact-surface counts/precision/recall/F1; it never emits private phrases. A
  critical aggregate requires one policy on every case and rejects mixed policy
  identities. Public aggregates omit even the policy hash. Silence cases cannot
  carry this policy.
- Ordered critical scoring detects omissions, additions, substitutions, and
  swaps such as exchanging `5 mg` and `10 mL`, but it is not a general semantic
  medical-equivalence parser. Context-sensitive number/unit equivalence remains
  a separately gated fixture/review requirement; Phase 6 cannot claim it until
  that executable gate exists.
- The runtime matrix records model-independent `terminologyContextSupport` per
  system. The exact locked Cohere and Nemotron paths are `none`: Cohere's decoder
  control prefix and Nemotron's language/right-attention prompts are not
  provider-native terminology injection. The deferred live-server path remains
  `unverified`. A future supported path must amend the frozen plan and compare
  the same audio/policy with and without context while the private inference
  lock binds the source-policy and provider-request identities. This evidence
  format is not a product glossary store or synchronization design.
- The scorer bounds each input at one MiB, each unit sequence at 250,000, and
  both per-alignment and aggregate bit-parallel alignment work. Longer references
  must retain source-time segments and micro-aggregate edit counts and reference
  units; rates are never averaged across unequal utterances. Zero-reference
  cases stay out of WER denominators while retaining hallucinated insertions.
  The older Rust and Phase 4 Python WER helpers remain smoke-only diagnostics
  and cannot produce multilingual promotion claims.
- Silence/noise has a zero-word reference and an explicit false-words-per-minute
  and false-language-tag gate; a plausible sentence is a failure.

### Streaming behavior

- final WER/CER after the same normalization used for batch;
- audio-to-first-partial, audio-to-stable-prefix, endpoint/finalization latency,
  and p50/p95/p99;
- partial-hypothesis churn/flicker, words revised after first display, and words
  retracted after becoming stable;
- endpoint false cuts, clipped initial/final words, dropped audio frames,
  backlog, and sustained real-time factor; and
- exact final transcript parity between deterministic live replay and supported
  batch mode, except for explicitly documented model-mode differences.

### Runtime and lifecycle

- cold readiness/model load and warm request latency;
- wall time, real-time factor, audio-seconds/second, request throughput,
  p50/p95/p99, queue time, actual server batch sizes, and failure/rejection
  counts;
- GPU/CPU/RSS/cgroup current and peak memory, allocator/cache behavior, GPU
  utilization, and thermal/throttling observations;
- memory plateau over repeated waves, zero cgroup high/max/OOM/OOM-kill event
  deltas, bounded scratch/output,
  no leaked threads/processes/containers/listeners, and deterministic teardown;
- cancellation-intent-to-acknowledgement, recovery latency, restart/resume,
  retry idempotence, and result-publication uniqueness; and
- per-route and per-duration results. A better aggregate may not offset a
  correctness, privacy, or resource regression in a required slice.

Thresholds must be written before the frozen promotion run and tied to the
actual supported use. Performance comparisons use repeated warm measurements,
separate cold results, uncertainty intervals, and the exact same input/reference
set. Do not publish a p99 from fewer than 200 independent short completions;
one-off long cases report individual measurements. Long c1 cases may run once
inside the gate, but their integrity and resource assertions are deterministic.
Identity/hash mismatch, sentinel omission/duplication/reordering, cross-request
leakage, unknown references, failed frozen accuracy thresholds, OOM, unbounded
growth, failed cancellation recovery, or unsupported claims block promotion.
A token difference from adjudicated human gold is scored; it is not by itself a
structural failure.

On GB10, physical RSS can oscillate as already-reserved unified-memory pages
become resident and are reclaimed. The Phase 6 resource decision therefore
retains the cgroup-current regression/range as descriptive evidence but gates
boundedness on predeclared current/peak ceilings, stable CUDA counters where the
provider reports them, zero memory-event increments, bounded task/thread counts,
and the tail-window median of the container entrypoint's virtual allocation
extent. A flat endpoint alone is insufficient, and a residency slope alone is
not called a live-object leak.

## Executable implementation order

1. Add a bounded manifest schema/validator, external-cache resolver, license and
   SHA verification, and a transcript-free evidence schema.
2. Pin scorer/normalizer revisions and test them on hand-checked substitutions,
   Unicode, punctuation, numbers, speaker permutations, silence, and overlap.
3. Build a tiny hosted smoke suite and a stratified Phase 6 promotion subset;
   keep the extended and approved-private suites separately selectable.
4. Generate exact-duration sentinel tracks and fixed acoustic/transport
   transformations with reproducible manifests, never by mutating source truth.
5. Run each candidate through one harness that records model/runtime/artifact
   identity, per-slice quality, lifecycle, and resource evidence.
6. Conduct independent reference and result review, resolve findings, freeze the
   candidate and thresholds, then run the one-time complete Phase 6 matrix.

The initial Phase 6 promotion subset should be hours, not hundreds of hours, but
must contain every coverage row and advertised locale. The extended suite runs
before a model/runtime promotion or major decoder change. Phase 10 adds the
approved-private, authenticated mixed-owner and enterprise deployment profile.

## Primary references

- [NIST AI RMF Measure guidance](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)
- [ISO/IEC 25012 data quality model](https://www.iso.org/standard/35736.html)
- [NIST SCTK](https://github.com/usnistgov/SCTK)
- [MeetEval](https://github.com/fgnt/meeteval)
- [Streaming ASR quality and stability metrics](https://research.google/pubs/analyzing-the-quality-and-stability-of-a-streaming-end-to-end-on-device-speech-recognizer/)
- [AMI official download and CC BY 4.0 terms](https://groups.inf.ed.ac.uk/ami/download/)
- [AMI official scenario and ASR splits](https://groups.inf.ed.ac.uk/ami/corpus/datasets.shtml)
- [AMI transcription process and known limitations](https://groups.inf.ed.ac.uk/ami/corpus/transcription.shtml)
- [AMI documented corpus data problems](https://groups.inf.ed.ac.uk/ami/corpus/dataproblems.shtml)
- [Nemotron 3.5 training and evaluation datasets](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b#training-and-evaluation-datasets)
- [Locked Nemotron 3.5 model contract](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b/tree/f3d333391852ba876df169dcc9ba902d25b6ab0b)
- [Nemotron English training and leaderboard datasets](https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b#datasets)
- [Cohere Transcribe model limitations](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026#strengths-and-limitations)
- [Locked Cohere Transcribe model contract](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026/tree/b1eacc2686a3d08ceaae5f24a88b1d519620bc09)
- [European Parliament multimedia reuse terms](https://www.europarl.europa.eu/legal-notice/en)
- [European Parliament plenary transcript and video semantics](https://www.europarl.europa.eu/plenary/en/debates-video.html)
- [ESB multi-domain benchmark design](https://arxiv.org/abs/2210.13352)
- [Earnings-21 transcript-license scope](https://github.com/revdotcom/speech-datasets/blob/main/earnings21/LICENSE.md)
- [Earnings-22 transcript-license scope](https://github.com/revdotcom/speech-datasets/blob/main/earnings22/LICENSE.md)
- [RWCP owner licensing and use restrictions](https://research.nii.ac.jp/src/en/RWCP-SSD.html)
- [LibriCSS repository license](https://raw.githubusercontent.com/chenzhuo1011/libri_css/master/LICENSE)
