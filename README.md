# 🎬 AI Vlog Editor

> Working product name: **Cutory** (WIP)
>
> 사용자의 편집 의도는 남기고, 반복적인 영상 편집 노동은 AI에게 맡깁니다.

AI Vlog Editor는 촬영 중 남긴 음성 편집 메모를 이용해 긴 브이로그 원본에서 필요한 장면을 찾고, 실제 영상 결과물로 만드는 프로젝트입니다.

사용자의 창작 판단을 AI가 대신하는 것보다, 사용자가 이미 내린 판단을 탐색·구조화·실행하는 데 집중합니다.

## Core Idea

촬영하면서 다음과 같이 편집 의도를 남깁니다.

> “AI야 방금 장면 꼭 살려줘.”

시스템은 업로드된 영상에서 해당 발화와 타임스탬프를 찾고, “방금”이 가리키는 장면 후보를 선택해 실제 MP4 클립으로 추출합니다.

## MVP v1

```text
Video → Audio → STT → Timestamp → Edit Memo → Candidate Interval → Evaluation → FFmpeg → MP4
```

초기에는 복잡한 LLM/VLM 판단 대신 메모 이전 5·10·15·30초를 선택하는 규칙 기반 Baseline을 비교합니다. Ground Truth와의 IoU를 측정하고 실패 사례가 다음 기술의 필요성을 결정합니다.

## Roadmap

1. **MVP Baseline** — 음성 메모 탐지와 실제 장면 추출
2. **Scene Retrieval Improvement** — 장면 경계와 의미 검색 개선
3. **Conversational Editing** — 자연어 수정 요청을 편집 작업으로 변환
4. **Personalization** — 사용자 편집 선호 반영
5. **Narrative Editing** — 여러 장면을 하나의 이야기로 구성
6. **Multi-platform Short-form** — Shorts/Reels용 편집안과 실제 영상 생성
7. **Agent Workflow Review** — 동적 재계획 필요성이 확인된 뒤 검토

## Technology Strategy

### MVP v1

- Python
- FastAPI
- FFmpeg
- STT — 엔진 미정

### 필요성이 검증된 이후

- Embedding / Semantic Search
- LLM / VLM
- 데이터베이스와 Object Storage
- Tool Calling / Agent Workflow

기술을 먼저 선택하지 않고 `Baseline → Evaluation → Failure Analysis → Improvement` 순서로 도입합니다.

## Documentation

- [Product Specification](docs/product-spec.md)
- [MVP v1 Specification](docs/mvp-v1-spec.md)
- [Architecture](docs/architecture.md)
- [Project Plan](docs/project-plan.md)
- [UI / UX Design](docs/ui-design.md)
- [Evaluation Dataset v0.1](evaluation/README.md)
- [Codex Project Instructions](AGENTS.md)

## Current Repository Status

2026-09-07 현재 저장소에서 확인된 상태입니다.

- [x] 프로젝트 문제와 제품 원칙 정의
- [x] MVP v1 범위 및 평가 전략 정의
- [x] Evaluation Dataset v0.1 시나리오 설계
- [x] Test 01 촬영 및 Ground Truth 기록
- [x] FastAPI 기본 환경과 `GET /health`
- [x] `POST /videos/upload` — 업로드 파일명과 Content-Type 확인
- [ ] 업로드 파일 검증 및 안전한 로컬 저장
- [ ] FFmpeg 오디오 추출
- [ ] STT 후보 비교 및 Baseline 구현
- [ ] 편집 메모와 타임스탬프 탐지
- [ ] 5·10·15·30초 후보 및 IoU 평가
- [ ] FFmpeg 기반 실제 클립 생성

원본 테스트 영상은 개인정보와 용량 문제로 Git에 포함하지 않습니다.

## Run the Current API

```powershell
python -m uvicorn app.main:app --reload
```

실행 후 `/health`에서 현재 API 상태를 확인할 수 있습니다.
