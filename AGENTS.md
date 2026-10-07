# AI Vlog Editor 작업 지침

## 프로젝트 원칙

- 사용자가 창작 판단을 내리고, 시스템은 탐색·추론·실행의 반복 노동을 줄인다.
- 텍스트 조언으로 끝내지 않고 실제 영상 파일 또는 검증 가능한 편집 계획을 만든다.
- 새 기술은 Baseline의 실패와 평가 결과가 필요성을 보여줄 때 도입한다.
- 구현 순서는 `Baseline → Evaluation → Failure Analysis → Improvement`를 따른다.
- 원본 영상과 음성에는 개인정보가 포함될 수 있으므로 Git에 추가하지 않는다.

## 현재 범위

- Version Roadmap의 `v1 — Project & Large Video Foundation`은 완료됐다.
- 완료 범위와 근거는 `docs/roadmap/v1-plan.md`, `docs/roadmap/v1-completion.md`, `evaluation/results/cutory-v1-foundation-eval-v0.1.md`를 따른다.
- `v2 — Tool / MCP & Scene Intelligence`의 Detailed Plan이 수립됐으며 `docs/roadmap/v2-plan.md`를 현재 v2 구현의 Source of Truth로 사용한다.
- v2는 Structural/Foundation Implementation Complete 상태이며 Gap Closure를 진행 중이다. G4-A/B/C와 G5-A review, G5-B1 focused dataset schema/annotation guide는 완료됐고, G5-B2 recording manifest 및 G2/G3는 pending이며 G1 actual Text LLM evaluation은 `BLOCKED_NO_API_KEY`다. 실제 controlled media는 촬영되지 않았고 GT도 freeze되지 않았다. v2는 observed Evidence를 소유하고 SceneRole은 v3에서 Scene Agent의 optional/non-authoritative hint와 Edit Planner의 authoritative SceneEditPlan role로 분리한다. v2 전체를 Completed로 과장하거나 Distributed queue/lock, semantic Event relation, VLM, Scene Agent, LangGraph, Multi-Agent, RAG, Creative Editing, Reviewer, Final Mobile App, Short-form을 앞당기지 않는다.
- 미결정 사항을 임의로 확정하거나 포트폴리오 목적만으로 기술을 추가하지 않는다.

## 기준 문서

제품 방향과 현재 Version 범위가 충돌할 때 다음 순서로 판단한다.

1. Full Product: `docs/product/full-development-plan.md`
2. Version 구현 순서: `docs/roadmap/version-roadmap.md`
3. 완료된 v1: `docs/roadmap/v1-plan.md`, `docs/roadmap/v1-completion.md`, `evaluation/results/cutory-v1-foundation-eval-v0.1.md`
4. 현재 Version Detailed Plan: `docs/roadmap/v2-plan.md`
5. Historical Baseline: `docs/mvp-v1-spec.md`, `evaluation/results/`의 과거 실험, `docs/integration-eval01-v0.1.md`, `docs/browser-e2e-v0.1.md`

현재 저장소의 코드와 자동화된 테스트는 이미 구현된 사실의 기준이다. 문서와 코드가 다르면 차이를 숨기지 말고 먼저 보고하되, 과거 Baseline 문서로 완료된 v1 범위를 축소하지 않는다.

`docs/mvp-v1-spec.md`의 “MVP v1”은 현재 Version Roadmap의 v1과 다른 단일 영상 Baseline의 역사적 명칭이다. 기존 Evaluation과 통합 검증 기록도 Baseline history로 보존하며 현재 Version의 Scope 문서로 사용하지 않는다.

## 구현 규칙

- Python, FastAPI, FFmpeg를 기본으로 사용한다. STT 엔진은 비교 실험 전 확정하지 않는다.
- 결정적인 파일 처리·시간 계산·FFmpeg 실행·IoU 평가는 일반 코드로 구현한다.
- 확률적 모델의 출력과 결정적인 실행 단계를 분리하고, 중간 결과를 구조화된 데이터로 남긴다.
- 외부 모델이나 새 운영 의존성을 추가하기 전에 목적, 대안, 비용, 개인정보 영향을 기록한다.
- 원본 영상은 `evaluation/data/`에 로컬로 둘 수 있지만 Git에는 추가하지 않는다.
- 기능 변경 시 관련 명세와 평가 문서를 함께 갱신한다.

## 완료 기준

- 요청된 동작이 실제로 실행된다.
- 정상 경로와 주요 실패 경로를 검증한다.
- 모델 또는 알고리즘 결과는 Ground Truth나 명시적인 기준과 비교한다.
- 구현 상태를 README에 과장해 표시하지 않는다.
