# Shot Structure deterministic baseline v0.1

## Run identity

- Capability: deterministic Shot Structure Evidence
- Detector: FFmpeg `scdet`
- Detector version: `ffmpeg-scdet-v0.1`
- Dataset: temporary synthetic shot-focused fixtures
- Threshold: 10 percent
- Minimum shot duration: 0.5 seconds
- Boundary tolerance: ±0.15 seconds, fixed before execution
- LLM calls: 0
- VLM calls: 0

## Current result

`COMPLETED`

The installed FFmpeg 9.0.1 executable was resolved outside `PATH` and supplied to
the validation process without persisting its absolute path. Its `scdet` filter was
available. The evaluation runner generated all fixtures under a temporary directory,
executed the real detector, and cleaned the media when the run ended.

## Planned synthetic fixtures

1. one continuous static shot;
2. two static color segments with one hard cut;
3. four static color segments with three hard cuts;
4. one continuous moving `testsrc2` source to observe camera-motion-like false positives.

The runner creates every fixture in a temporary directory and removes it after the
run. No generated media is committed.

## Metrics

| Metric | Result |
|---|---:|
| Fixtures executed | 4 |
| GT boundaries | 4 |
| Detected boundaries | 4 |
| True positives | 4 |
| False positives | 0 |
| False negatives | 0 |
| Precision | 1.0 |
| Recall | 1.0 |
| F1 | 1.0 |
| Mean boundary timing error | 0.0 seconds |
| Zero-boundary actual-media correctness | PASS |
| Continuous-motion false positives | 0 |
| Fade/dissolve | NOT_TESTED |
| Runtime | 0.205085 seconds |
| Runtime/source-minute | 0.769070 seconds |

## PostgreSQL

The opt-in integration suite ran against the existing PostgreSQL 17.11 container.
All three Shot-specific scenarios passed: durable nonzero-boundary Candidate Evidence
with new-session reload and same-spec reuse, zero-boundary completion with source
fingerprint invalidation, and detector-failure isolation. The complete 29-test
PostgreSQL integration suite also passed. Alembic reported revision
`a7e9c4d1f2b8 (head)` and no schema drift.

## Limitations

- Metrics are from four synthetic fixtures and are not production vlog accuracy.
- The baseline targets hard cuts and jump cuts. Fade/dissolve support is unverified.
- FFmpeg `scdet` can react to flashes or sufficiently large within-shot changes.
- Shot boundaries do not create Candidates, change Candidate intervals, assign SceneRole,
  or infer Events.
- The complete Shot manifest is bounded inside the WorkItem result reference; there is
  intentionally no Shot Product table.
