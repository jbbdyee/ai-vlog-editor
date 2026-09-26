# Cutory RAG and Retrieval Architecture

## 목적

검색이 유효한 비구조화 지식/사례/음악에만 RAG를 사용하고 profile, plan, license, workflow state는 DB lookup으로 분리한다.

## 1. Editing Knowledge RAG

Storytelling, pacing, B-roll, caption, audio, color, short-form 편집 지식을 KnowledgeDocument/KnowledgeChunk로 관리한다. Edit Planner, Creative Agent, Reviewer가 현재 task에 필요한 chunk만 검색한다. 출처, version, scope, applicability를 보존한다.

## 2. User Style Reference RAG

UserStyleProfile은 구조화된 장기 선호이고, StyleReference는 과거 승인/수정 사례다. 둘을 합치지 않는다. Style Agent는 상황이 비슷한 사례를 검색해 profile을 보조하되, 검색 사례가 explicit instruction/profile을 덮지 못하게 한다.

## 3. BGM Semantic Retrieval

Approved BGM Catalog 안에서 Scene/Creative Intent에 맞는 음악을 `Metadata Filter + Semantic Search`로 찾는다. mood, genre, energy, vocal, duration을 검색에 사용할 수 있지만 license eligibility는 vector similarity가 아닌 구조화 DB validator가 판단한다.

## 입력과 출력

Input은 user/project scope, query/context, metadata filters, top-k/threshold policy다. Output은 resource/chunk/reference IDs, score, source metadata, retrieval version이며 full binary나 새 실행 명령을 포함하지 않는다.

## RAG를 사용하지 않는 데이터

- UserStyleProfile, ProjectStyle
- Font/BGM/SFX license
- ColorPreset
- EditPlan/CreativePlan
- Workflow state

이들은 relational DB와 structured lookup을 사용한다.

## 개인정보/격리

StyleReference와 query는 user/project scope로 격리한다. 장기 참조 생성은 사용자가 승인한 편집/수정에서만 이루어지며, binary 대신 최소 구조화 특징과 안전한 reference를 저장한다.

## 실패 처리

Knowledge/Style retrieval 실패는 구조화 policy/default와 warning으로 계속할 수 있다. BGM retrieval 실패는 BGM 없는 CreativePlan으로 degradation한다. 단 출처 없는 지식을 retrieval result로 위장하지 않는다.

## 하지 않는 일

RAG로 license, workflow state, exact profile 값을 결정하지 않고, Vector DB를 모든 데이터의 기본 저장소로 사용하지 않는다.

## 향후 확장

Embedding model, vector store, chunk strategy, freshness/evaluation, style-reference retention은 별도 평가로 결정한다.
