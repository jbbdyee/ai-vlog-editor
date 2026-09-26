# Large Video Processing Architecture

## 목적

100+ 영상, 수 시간 footage를 중복 분석 없이 점진적·병렬화 가능하게 처리하고, 비싼 AI를 필요한 후보에만 사용한다.

## 입력

- Project ID, SourceVideo resource IDs
- 파일 metadata/ingestion state
- Project instruction와 analysis policy
- 기존 stage result/version/fingerprint

## 출력

- SourceVideo 별 analysis state
- MediaInfo, Transcript, EditMemo
- Shot/Audio/Quality signal
- Scene segments, Evidence, QualityFlags
- reduced candidates 및 deep-analysis request
- warning/failure/resume metadata

## Cheap → Expensive Analysis

```text
100+ Source Videos
→ Incremental Ingestion
→ Probe / Audio / STT / Memo / Shot / Quality
→ Scene Segmentation and Evidence Collection
→ Deduplication / Candidate Reduction
→ LLM/VLM Deep Analysis for selected intervals only
```

Autonomous Discovery는 전체 footage를 대상으로 하지만 모든 frame을 같은 비용으로 분석한다는 뜻은 아니다. deterministic signal이 후보를 만들고 의미 분석은 축소된 구간에 집중한다.

## Incremental / Resumable Processing

각 SourceVideo와 stage는 `PENDING`, `ANALYZING`, `ANALYZED`, `FAILED`, `SKIPPED` 같은 명시적 상태와 input fingerprint, output version을 갖는다.

```text
127 sources
96 ANALYZED
1 ANALYZING
30 PENDING
```

중단 후에는 96개의 유효한 산출물을 재사용하고 미완료/무효화 stage만 재개한다. Config/model/tool version이 바뀌어 산출물이 무효화되는 조건은 명시적으로 기록한다.

## Parallelizable Media Analysis

Source 단위 probe, audio extraction, STT, frame/shot/quality 분석은 dependency와 resource budget 내에서 병렬화할 수 있다. 단 GPU/CPU/memory/disk I/O 한도와 공유 모델 thread-safety를 실행계에서 제한한다. 정확한 worker/queue 기술은 미결정이다.

## Partial Failure Tolerance

- 오디오 없음: visual-only 가능성과 제약을 기록
- 손상/unsupported source: source-level failure, project warning
- STT 실패: transcript evidence 없음을 명시, 정책에 따라 retry/제외
- 1/100 source 실패: 프로젝트 전체를 즉시 실패시키지 않음
- 필수 이벤트의 유일 소스 실패: 사용자 판단 요청 가능

## Temporary Artifact Lifecycle

WAV, extracted frame, contact sheet, proxy, intermediate clip은 project/source/stage 소유권을 갖는 temporary workspace에 두고 완료·취소·TTL 정책에 따라 삭제한다. Source, approved preview, final render는 중간 파일과 다른 보존 정책을 사용한다.

## Scene / Event 연결

파일 별 Scene은 후속 Cross-video Event Grouping에서 `SAME_EVENT`, `CONTINUATION`, `REACTION_TO`, `ALTERNATIVE`로 연결된다. 이 단계는 파일 처리가 일부 완료될 때 점진적으로 갱신될 수 있어야 한다.

## 다른 Component와의 관계

Ingestion은 resource ID를 발급하고, Tool Layer는 분석을 실행하며, Scene Agent는 구조화 Evidence와 reduced candidate를 해석한다. Orchestrator는 상태·resume·retry를 관리한다.

## 하지 않는 일

- 100+ 원본을 하나의 LLM/VLM prompt로 전송
- 이미 성공한 분석의 무조건 재실행
- 일부 source 실패를 무조건 전체 project 실패로 승격

## 향후 확장

실제 concurrency, queue, worker, priority, backpressure, checksum/cache policy는 운영 규모 평가 후 확정한다.
