# Scene Intelligence Resume / Reprocess v0.1

- Run: `scene-resume-reprocess-v0.1`
- Dataset: synthetic execution-lineage and 600-Candidate scale mechanics
- PostgreSQL: actual local PostgreSQL 17.11 integration suite executed
- Semantic accuracy: not evaluated
- LLM/VLM calls: 0 / 0

## Verified behavior

- Completed work is reused only when input/config/producer and the work-specific result contract remain valid.
- Candidate-free autonomous completion and semantic abstention remain reusable results.
- Scene Work retry adds a new Attempt; stale RUNNING recovery requires a caller cutoff.
- Candidate result links make the latest valid Work result authoritative without deleting older Candidate rows.
- Transcript, Audio and Visual WorkItems now use independent input/config/result fingerprints.
- An Audio config change re-executes Audio analysis while cached Transcript and Visual manifests are reused. When the canonical Audio result is unchanged, Promotion and Event work remain reusable.
- Accepted `SAME_EVENT` relation changes invalidate grouping even when the Candidate snapshot is unchanged.
- Candidate/Evidence and EventGroup/Member writes use their existing bounded transaction scopes; injected service errors are rolled back before a WorkItem failure is recorded.

## Scale result

- Candidate count: 600
- Full possible pairs: 179,700
- Full retained pairs: 599
- One-Candidate incremental possible pairs: 599
- One-Candidate incremental retained pairs: 1
- The scale fixture measures reuse, pair scope and runtime mechanics only; it has no semantic Event ground truth.

## Known limitations

- Work claiming uses PostgreSQL parent-row locks and rechecks, not a distributed lock or durable worker.
- The active Candidate resolver selects the newest valid Work per logical source/target scope; it is current-state lineage, not immutable result history.
- No automatic scheduler, background stale recovery or infinite retry exists.
- Actual OpenAI semantic quality and VLM behavior remain unverified/out of scope.
