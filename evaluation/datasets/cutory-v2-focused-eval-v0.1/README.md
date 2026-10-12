# Cutory v2 focused evaluation dataset v0.1

Status: **G5-B1/B2 contracts and G5-B5 media-free Validator implemented**. Eight unfrozen P1 GT drafts are present; P2/P3 GT and selected Memo/VLM/Event references remain incomplete. This Windows checkout has no controlled media. There is no frozen GT case, provider result, or semantic accuracy result yet. The v2 version completion gate remains open.

This focused dataset will measure four distinct questions against controlled local vlog media:

| View | Question | GT authority |
| --- | --- | --- |
| A Memo | Can the deterministic selector or selective Text LLM choose an existing proposal, or abstain correctly? | Memo intent, target interval, semantic outcome; proposal ID mapping is derived |
| B Autonomous | Are meaningful intervals retained with appropriate observed Evidence? | Human `should_consider` intervals and observable facts |
| C VLM | Does bounded visual input resolve a specific proposal ambiguity? | Visual sufficiency of the exact bounded representation |
| D Event | Are cross-video relations and conservative groups correct? | Focused pairs, event membership, must-not-merge |

The historical `evaluation/README.md` and `evaluation/results/` describe earlier runs. They are not this dataset's GT. Current `evaluation/data/` has no source media.

## Directory contract

```text
evaluation/datasets/cutory-v2-focused-eval-v0.1/
  README.md
  ANNOTATION_GUIDE.md
  schema/
    common.schema.json
    memo.schema.json
    autonomous.schema.json
    vlm.schema.json
    event.schema.json
  manifests/
    README.md
    recording-scenarios.json
    COVERAGE.md
    RECORDING_CHECKLIST.md
  annotations/
    README.md
evaluation/data/                  # ignored local raw media; never commit
evaluation/tmp/                   # ignored runtime payloads; never commit
```

Schemas use JSON Schema Draft 2020-12. The [G5-B5 Validator](../../validate_focused_gt.py) combines schema checks with cross-field interval bounds, candidate ownership, symmetric pair order, and referenced IDs. It supports `draft` and `freeze-ready` without media; see [annotations/README.md](annotations/README.md). It cannot establish semantic truth, visual sufficiency, hash-to-media equality, or human freeze approval. Schema `examples` contain deliberately incomplete **annotation fragments** with `EXAMPLE-*` IDs. They are illustrations, not real cases or valid complete source records. No dummy media hash is supplied.

## Versions and freeze

- Dataset ID: `cutory-v2-focused-eval-v0.1`.
- `annotation_revision` starts at 1 and is separate from dataset, algorithm/config, prompt/schema, and provider/model run versions.
- Each Project may be recorded, fingerprinted, annotated, then frozen independently. **All three Projects of v0.1 must be frozen before any Text LLM, VLM, or semantic Event Provider evaluation.**
- `annotated_before_model_run: false` excludes an annotation from the primary preregistered benchmark. A post-run correction gets a new revision and reason; it does not overwrite the original run or result.
- Proposal IDs are derived from a fixed local proposal generator and config. First freeze media-level intent/interval GT; then generate the proposal manifest and freeze acceptable ID mapping **before** calling a provider. Keep the manifest fingerprint alongside that mapping. An empty set is valid for abstention outcomes.

For Dataset B, a GT target is recalled only if **target coverage ≥ 0.70 AND tIoU ≥ 0.30**. Both thresholds are fixed before v0.1 evaluation. They prevent a very long Candidate from earning recall solely by covering a short target. Do not tune them after viewing v0.1 results. Report reduction rate together with GT recall.

See [ANNOTATION_GUIDE.md](ANNOTATION_GUIDE.md) for recording, relation, ambiguity, privacy, and leakage rules. G5-B2 preregistered the [recording manifest](manifests/recording-scenarios.json), [coverage](manifests/COVERAGE.md), and [filming checklist](manifests/RECORDING_CHECKLIST.md). G5-B3/B4 controlled recording and GT annotation are only partial; eight P1 drafts are unfrozen. G1 is `BLOCKED_NO_API_KEY`; G2/G3 remain pending.
