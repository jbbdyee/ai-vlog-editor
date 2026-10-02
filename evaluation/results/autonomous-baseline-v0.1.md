# Autonomous Scene Discovery deterministic baseline v0.1

## Run scope

- version: `autonomous-discovery-v0.1`
- runner: `evaluation/run_autonomous_baseline.py`
- dataset: 3개 synthetic signal-level scenario
- actual media: 없음
- semantic Ground Truth: 없음
- LLM calls: 0
- VLM calls: 0

Repository의 `evaluation/data/`에는 실제 Autonomous focused video가 없다. 인터넷 다운로드나 사용자 영상 생성을 하지 않았으며, 아래 결과를 real-media 정확도나 semantic quality로 해석하지 않는다.

## Signals and promotion

- Transcript: segment structure, speech presence, 최소 lexical reaction cue `우와`, `와`, `대박`, `헐`
- Audio: PCM16 RMS activity, silence, long silence
- Visual: FFmpeg grayscale frame difference activity, static interval
- Quality: `LONG_SILENCE`, `STATIC_INTERVAL`
- Promotion: reaction+audio, transcript structure+audio, audio+visual의 interval overlap
- Single signal과 quality-only signal: abstain

## Synthetic result

명령: `.\.venv\Scripts\python.exe -m evaluation.run_autonomous_baseline`

- cases: 3
- Candidate count: 2
- Candidate duration: 12.0초
- 전체 synthetic source duration 대비 Candidate ratio: 0.08333
- Candidates/minute: 0.83333
- Evidence input count: Transcript 1, Audio 2, Visual 1, Quality 2
- Abstention: 1 (`quality_only`)
- Partial modality failure: 1 (`TRANSCRIPT_ANALYSIS_FAILED`)
- exact duplicate output: 0
- Candidate Recall/Precision: GT가 없어 계산 불가
- Reduction Rate/GT Recall after reduction: GT와 initial candidate universe가 없어 계산 불가

## Failure taxonomy

| type | count |
|---|---:|
| `MODALITY_PARTIAL_FAILURE` | 1 |
| `INSUFFICIENT_CROSS_MODAL_EVIDENCE` | 1 |
| `ALL_MODALITIES_FAILED` | 0 |
| `PROMOTION_FAILURE` | 0 |
| `PERSISTENCE_FAILURE` | 0 |

## Known limitations / Step 6 handoff

Signal은 의미 중요도를 나타내지 않는다. 현재 reaction cue는 매우 작은 lexical set이며 STT 오인식, 한국어 활용형, 실제 웃음·박수 같은 non-speech 의미를 이해하지 못한다. Audio/visual activity가 우연히 겹쳐도 semantic highlight라는 보장은 없다. 반대로 visual-only event와 quiet but important scene은 abstain될 수 있다. 실제 focused media와 사람이 정의한 GT를 준비한 뒤 proposal miss, false promotion, abstention을 분리 측정해야 하며, 그 결과가 selective LLM/VLM의 필요 범위가 된다.
