# Ground Truth annotation guide

This guide is for a person watching the controlled recordings. Ground Truth (GT) means the answer recorded **before** viewing model output. It describes the intended scene, observed facts, or real-world Event. It is not a preferred output invented after a model run.

## 촬영·정답 기록 빠른 안내

GT는 사람이 영상을 보고 **모델을 실행하기 전에** 적어 두는 정답이다. G5-B1에는 아직 실제 영상이나 정답이 없다. 촬영 전에 다음 장면에서 무엇을 보여줄지 간단히 적고, 촬영 뒤 원본을 보며 실제 시간을 기록한다. 모델이 고른 결과를 본 후 시간을 옮겨 적지 않는다.

1. 영상마다 `EXAMPLE-SOURCE` 같은 개인 정보가 없는 ID를 붙인다. 파일명에 “정답 장면” 같은 답을 넣지 않는다.
2. 해당 장면의 시작과 끝을 원본 영상의 초 단위로 적는다. 예를 들어 물건을 집어 들기 시작한 4.2초부터 내려놓은 6.8초까지라면 `4.2–6.8`이다. 경계가 애매하면 이유를 함께 적는다.
3. 메모 평가에서는 메모가 가리킨 장면이 하나인지, 둘 이상 모두 합당한지, 정말 구별할 수 없는지, 근거가 부족한지, 아예 없는지 구분한다. 둘 이상 모두 합당하면 여러 Proposal을 허용한다. 구별 자체가 불가능하면 `AMBIGUOUS`다.
4. 메모 없이 찾는 장면은 “검토할 후보로 남겨야 하는가”를 적는다. 최종 영상에서의 `B_ROLL`·`STORY` 같은 역할은 적지 않는다.
5. 시각 평가에서는 전체 영상을 알고 있더라도, 모델에 보낼 제한된 3-frame contact sheet만 보고 판단 가능한지 따로 적는다.
6. 여러 파일이 같은 실제 활동을 보여주는지 적는다. 같은 장소에서 다음 날 찍은 영상은 별도 Event일 수 있다. 반응 관계는 반드시 **반응 장면 → 원인 장면** 순서로 기록한다.
7. Project 하나를 촬영하고 정답을 고정할 수 있다. 다만 세 Project 모두 고정되기 전에는 실제 semantic Provider를 실행하지 않는다.

정답이 불명확할 때 억지로 한 장면을 선택하지 않는다. `AMBIGUOUS`는 여러 후보를 구별할 수 없음, `NO_MATCH`는 해당 장면이 없음, `INSUFFICIENT_EVIDENCE`는 현재 제한된 정보로 판단할 수 없음을 뜻한다. Provider 오류는 이 세 정답 중 어느 것도 아니다. 원본 영상은 로컬 `evaluation/data/`에만 보관하고 Git에 추가하지 않는다. 얼굴이 담긴 frame은 v0.1 외부 VLM에 보내지 않는다.

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
