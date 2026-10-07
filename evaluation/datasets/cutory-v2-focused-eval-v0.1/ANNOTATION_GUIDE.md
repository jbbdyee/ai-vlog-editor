# Ground Truth annotation guide

This guide is for a person watching the controlled recordings. Ground Truth (GT) means the answer recorded **before** viewing model output. It describes the intended scene, observed facts, or real-world Event. It is not a preferred output invented after a model run.

## Order of work

1. Register the scenario intent in a G5-B2 manifest before filming.
2. Record one Project. Store raw media under ignored `evaluation/data/` and assign opaque Project, Source, Memo, and Candidate references.
3. Calculate SHA-256 from each original file and record its duration. Annotate the Project without reading selector/provider output.
4. Freeze that Project's annotation revision. Repeat for all three v0.1 Projects.
5. Run a fixed local proposal generator, map acceptable proposals to the already frozen interval/intent GT, record the proposal manifest fingerprint, then freeze this **derived ID mapping before provider calls**.
6. Only after the complete v0.1 GT and derived mappings are frozen may actual Text LLM, VLM, or semantic Event Provider evaluation begin.

`annotated_before_model_run` must be true for the primary preregistered result. A later correction increments `annotation_revision`, records why it changed, and is compared as a separate revision. Preserve the earlier annotation and run result. A false value is excluded from the primary benchmark.

## Source envelope and intervals

Every source annotation identifies `dataset_version`, `annotation_revision`, opaque `project_id`, `scenario_id`, `source_id`, original `media_sha256`, `duration_seconds`, `annotated_before_model_run`, `annotator`, `annotation_time`, and `privacy_class: PRIVATE_LOCAL`. Event documents list a common envelope for each participating source and keep relation/group GT at Project scope.

Use seconds from the start of the original file: `0 <= start_seconds < end_seconds <= duration_seconds`. Record to **0.001 seconds** when playback permits; do not imply millisecond observation accuracy where the moment is unclear. This matches current Event/Shot interval normalization. Mark the first frame where meaningful action begins and the last moment it continues. If a cut or gradual action makes the edge uncertain, record `ambiguity` and `rationale_code`; do not move the edge to match a model. G5-B5 validates cross-field bounds because JSON Schema alone does not compare start/end/duration portably.

SHA-256 binds GT to exact bytes. Re-encoding or trimming creates new bytes and requires a new media identity and review of timestamps/GT. An exact byte copy may have the same SHA-256 while remaining a separate `source_id`; this is how an exact duplicate upload can be evaluated. A mismatch blocks evaluation for that source.

## A. Memo semantic selection

Annotate the Memo interval, temporal reference (`JUST_NOW`, `EARLIER`, `UNKNOWN`), expected outcome, target intervals, rationale, and ambiguity. `SELECTED` means at least one fixed generated Proposal ID is acceptable. Multiple acceptable IDs are allowed. An optional preferred ID records preference without making other acceptable IDs wrong. Proposal IDs and their manifest fingerprint are a **derived annotation layer**, frozen after proposal generation and before provider invocation. If no proposal covers the intended target, record a proposal miss separately; do not label a poor Proposal as correct.

`AMBIGUOUS` means the available evidence genuinely cannot distinguish alternatives. `NO_MATCH` means the referenced scene is absent from the allowed search material. `INSUFFICIENT_EVIDENCE` means the scene may exist but the bounded transcript does not support a safe choice. These outcomes use an empty acceptable-ID set. Provider timeout or invalid output is an execution failure, never semantic abstention.

## B. Autonomous Candidate and Evidence

For each meaningful or negative interval, annotate `should_consider`, `should_exclude`, real action/event and reaction presence, explicit user value, technical issues, and expected observations. These are v2 observed facts and utility signals, not final SceneRole. `STORY`, `B_ROLL`, `TRANSITION`, `ESTABLISHING`, and final `HIGHLIGHT` are Planner decisions and cannot appear in Autonomous GT.

Allowed production modalities include `MEMO`, `TRANSCRIPT`, `AUDIO`, `VISUAL`, `SHOT`, `QUALITY`, `MULTIMODAL`; this focused observation schema restricts itself to the five relevant autonomous/shot modalities. Current observation types are `TRANSCRIPT_STRUCTURE`, `TRANSCRIPT_REACTION_CUE`, `AUDIO_ACTIVITY`, `SILENCE`, `LONG_SILENCE`, `VISUAL_ACTIVITY`, `STATIC_INTERVAL`, and `SHOT_CHANGE`. `LONG_SILENCE` and `STATIC_INTERVAL` are quality observations in current code. Technical issues in the first schema are limited to those implemented types; a different issue needs a later schema revision, not a fabricated production enum.

A target is recalled iff target coverage ≥ 0.70 **and** tIoU ≥ 0.30. A very long Candidate may cover a target but fail tIoU. Report Candidate reduction with GT recall, missed quiet scenes, and false promotion. A low-quality interval can still have explicit user value. `should_consider` and `should_exclude` cannot both be true.

## C. Selective VLM

Annotate whether the exact **bounded Provider representation** contains enough information, not whether a person watching the full original video knows the answer. The initial comparison unit is a proposal manifest plus 3-frame (10%/50%/90%) contact sheet per proposal and bounded context. Its current code config version is `proposal-contact-sheet-v0.2`. Keep representation and proposal manifest versions fixed within a run. `SELECTED` maps to existing Proposal IDs; `AMBIGUOUS`, `NO_MATCH`, and `INSUFFICIENT_VISUAL_EVIDENCE` require abstention. A VLM never authors timestamps. Target intervals are for evaluator use after selection.

The v0.1 policy forbids sending any frame/contact sheet containing a personal face to an external VLM Provider. Record hands, objects, spaces, and actions where possible. A face-based reaction scenario needs separate privacy/provider review and a later dataset version.

## D. Cross-video Event relations and groups

An Event is one real activity or continuous experience, possibly across SourceVideos. Shared location, people, words, or objects alone do not prove `SAME_EVENT`: arriving home today and leaving the same home tomorrow are separate Events.

- `SAME_EVENT` and exact `DUPLICATE` are symmetric; record one canonical unordered pair. An exact duplicate follows the current deterministic contract: same source fingerprint and normalized exact interval. Similar footage from different cameras is not automatically `DUPLICATE`.
- `CONTINUATION` is directional and requires a real action flow. Opening a door followed immediately by setting down bags may qualify; the next day's departure does not qualify just because it is the next file. Record source as the earlier action and target as the continuation.
- `REACTION_TO` is directional: **source_candidate_id = reaction; target_candidate_id = trigger**. Example: `EXAMPLE-REACTION REACTION_TO EXAMPLE-TRIGGER`, where the first Candidate shows a response to the second Candidate's dropped cup. This is `REACTION → TRIGGER`.
- `UNRELATED`, `AMBIGUOUS`, and `INSUFFICIENT_EVIDENCE` are focused pair GT outcomes, not product `SceneRelationType` rows.

Relation GT and EventGroup GT are separate. First annotate real Event identity from media; after fixed Candidate generation, map those identities onto the `candidates` catalog and freeze the mapping before semantic Provider execution. A catalog entry ties an opaque Candidate ID to a source and interval. Put real Event membership in `event_groups`; `acceptable_unassigned` lists Candidates that may remain outside a group. `must_not_merge` lists two GT Event IDs whose fusion counts as overmerge. `ambiguous_memberships` can permit multiple GT Event IDs or `UNASSIGNED`. A single bridge pair does not automatically justify merging two groups. G5-B5 validates that all referenced Candidates and Events exist and that symmetric pairs use canonical order.

## Ambiguity and abstention scoring

Keep five cases distinct: one correct choice, multiple acceptable choices, genuinely ambiguous, insufficient evidence, and no match. Multiple acceptable Proposal IDs still expect `SELECTED`; an `AMBIGUOUS` label means a safe selector should abstain. Score correct abstention, false abstention, and false confident selection separately. Provider failure, timeout, parse failure, or validator rejection is reported in reliability metrics and cannot be relabeled as correct abstention.

## Leakage, privacy, and Git

Provider input contains only production-equivalent bounded Memo/transcript or face-free low-resolution visual evidence and opaque proposal IDs. Do not send GT intervals, acceptable/expected IDs, GT Event IDs, scenario answers, annotator notes, oracle scores, raw original video, paths, or credentials. Filenames must not encode answer labels. GT lookup happens only after selection and Python validation in the evaluator. Production `backend/` must never import evaluation GT.

Keep raw personal MOV/MP4/WAV, personal frames, and contact sheets local under ignored evaluation areas. Avoid addresses, vehicle plates, faces, and other personal details during recording. Commit only schema, guide, manifests, minimal timestamp/label GT with opaque IDs, and aggregate reports after privacy review. Never commit media, raw Provider payload, `.env`, secrets, absolute local paths, or temporary artifacts. Any change to external face-frame handling requires a separate review.
