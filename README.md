# 🎬 AI Vlog Editor

> 사용자의 편집 의도는 남기고, 반복적인 영상 편집 노동은 AI에게 맡깁니다.

AI Vlog Editor는 몇 시간 분량의 브이로그 원본에서 필요한 장면을 직접 찾아 편집해야 하는 문제를 줄이기 위한 AI 영상 편집 프로젝트입니다.

사용자가 촬영 중 남긴 자연어 편집 메모와 촬영 후 수정 요청을 이해하여 장면을 탐색하고, 실제 영상 편집까지 수행하는 것을 목표로 합니다.

## 💡 Core Idea

촬영하면서 간단하게 편집 의도를 남깁니다.

> "AI야 방금 장면 꼭 살려줘."

AI는 업로드된 영상에서 해당 발화를 탐지하고 타임스탬프와 영상 정보를 이용해 사용자가 의미한 장면을 찾습니다.

이후 장면 탐색, 컷 편집, 자막 생성 등 반복적인 작업을 AI가 수행하고 사용자는 결과에 대해 자연어로 수정 요청을 할 수 있습니다.

## 🎯 MVP

첫 번째 MVP의 목표는 하나의 핵심 파이프라인을 실제로 동작시키는 것입니다.

**Video → Audio → STT → Timestamp → Edit Intent → Scene → FFmpeg → MP4**

테스트 영상에서

> "AI야 방금 장면 꼭 살려줘."

라는 편집 메모를 탐지하고, 해당 메모가 가리키는 장면을 찾아 실제 MP4 클립으로 추출합니다.

## 🚀 Roadmap

- **v1** — 촬영 중 편집 메모 탐지 및 장면 추출
- **v2** — 자연어 기반 장면 검색
- **v3** — AI 브이로그 초안 생성
- **v4** — 자연어 기반 영상 수정
- **v5** — 사용자 편집 취향 학습 및 개인화
- **v6** — Multi-Agent 영상 편집 워크플로우

## 🛠 Tech Stack

기술은 개발 단계에서 실제 필요성이 확인될 때 점진적으로 도입합니다.

### MVP v1

- Python
- FastAPI
- FFmpeg
- STT

### Planned

- LLM
- Embedding / Semantic Search
- PostgreSQL / Supabase
- Redis
- Tool Calling
- Agent Workflow

## 🎨 UI / UX

초기 사용자 흐름과 UX 설계는 Figma Wireframe을 통해 검증하고 있습니다.

자세한 설계 과정과 변경 이유는 [`docs/ui-design.md`](docs/ui-design.md)에서 관리합니다.

## 📚 Documentation

- [`Project Plan`](docs/project-plan.md)
- [`UI / UX Design`](docs/ui-design.md)

## 📌 Project Status

**Current: MVP v1 Development**

- [x] 프로젝트 주제 및 문제 정의
- [x] 핵심 사용자 경험 정의
- [x] Figma Wireframe v0.1
- [x] MVP 범위 정의
- [x] MVP 평가 전략 및 Baseline 정의
- [x] FastAPI 개발 환경 구성
- [x] Health Check API
- [ ] 테스트 영상 및 Ground Truth 구성
- [ ] Video Upload API
- [ ] Video → STT 파이프라인
- [ ] 편집 메모 탐지
- [ ] Baseline 장면 탐색
- [ ] 장면 탐색 성능 평가
- [ ] FFmpeg 기반 장면 추출

