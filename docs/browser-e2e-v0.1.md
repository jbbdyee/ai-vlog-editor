# Browser End-to-End Integration Verification v0.1

## 1. 검증 목적

이 문서는 사용자가 실제 브라우저에서 Streamlit MVP를 조작해 FastAPI와 `VideoProcessingPipeline`을 거쳐 재생 가능한 MP4를 받을 수 있는지 확인한 End-to-End Integration Verification 결과다. 장면 선택 품질을 측정하는 Evaluation이 아니며, Ground Truth, IoU, Oracle은 사용하지 않았다.

## 2. 전체 사용자 흐름

```text
eval_01.MOV 업로드
→ Streamlit에서 5초 Window 선택
→ "영상 분석 및 클립 생성" 버튼 1회 클릭
→ POST /videos/process 1회
→ VideoProcessingPipeline COMPLETED
→ GET /videos/clips/{run_id}/{clip_id} 1회
→ Streamlit st.video() 재생
```

## 3. Backend / Frontend 실행 구성

- Backend: `.venv/bin/python -m uvicorn app.main:app`
- Frontend: `.venv/bin/python -m streamlit run frontend/app.py`
- Backend: reload 없이 단일 worker로 실행
- Frontend backend URL: 개발 기본값 `http://127.0.0.1:8000`
- Backend health: `GET /health` HTTP 200
- faster-whisper 모델: FastAPI lifespan에서 로드하여 요청에서 재사용

## 4. 입력 영상

- 파일: `evaluation/data/eval_01.MOV`
- 입력 방식: Streamlit MOV/MP4 uploader
- 처리 버튼 클릭: 1회
- Process API 호출: 1회

## 5. 사용자가 선택한 Window

사용자가 UI에서 **5초 Window**를 명시적으로 선택했다. 이 값은 AI가 최적이라고 판단한 결과가 아니며, 통합 경로를 검증하기 위한 deterministic 입력이다.

## 6. Transcript

STT 결과가 UI에 다음과 같이 표시되었다.

> 안녕하세요. 저는 김사과입니다. 지금은 간단한 동영상 테스트를 해보고 있습니다. 제가 물건을 하나 떨어뜨려 볼게요. 아 뭐야. 에이아이아 지금 장면 꼭 살려줘.

## 7. EditMemo

- 구간: 15.80~18.72초
- 문장: `에이아이아 지금 장면 꼭 살려줘.`
- trigger: `에이아이아`
- reference: `지금`
- action: `살려줘`

## 8. Candidate

| Window | Start | End |
| ---: | ---: | ---: |
| 5.00초 | 10.80초 | 15.80초 |
| 10.00초 | 5.80초 | 15.80초 |
| 15.00초 | 0.80초 | 15.80초 |
| 30.00초 | 0.00초 | 15.80초 |

## 9. Selection

- strategy: `fixed_window`
- source: `window:5.0`
- 선택 구간: 10.80~15.80초

이 결과는 UI에서 사용자가 명시한 5초 Window에 해당하는 Candidate를 `FixedWindowSceneSelector`가 결정적으로 선택한 것이다.

## 10. 생성 MP4

- duration: 5.00초
- video codec: H.264
- audio codec: AAC
- 파일 크기: 7,078,377 bytes
- FastAPI clip endpoint에서 `video/mp4`로 수신

## 11. 브라우저 재생 결과

Streamlit이 clip endpoint를 1회 호출해 받은 MP4 bytes를 `st.video()`에 전달했다. 브라우저에서 재생을 시작하고 5초 종료 지점까지 진행되는 것을 확인했다. 다운로드 버튼은 동일 MP4 bytes를 재사용했다.

## 12. File lifecycle

- 원본 `eval_01.MOV`: 보존
- UUID 기반 upload source: 보존
- run UUID directory: 생성
- intermediate WAV: Pipeline 종료 전 삭제
- run의 `audio/` directory: 비어 있음
- 최종 MP4: `clips/` 아래 보존

로컬 절대 경로는 HTTP 응답과 브라우저 UI에 노출하지 않았다.

## 13. Pipeline timing

| Stage | Duration |
| --- | ---: |
| output_preparation | 0.0002초 |
| media_probe | 0.0918초 |
| audio_extraction | 0.0795초 |
| stt | 2.5334초 |
| memo_detection | 0.0001초 |
| candidate_generation | 0.00001초 |
| candidate_selection | 0.00001초 |
| clip_rendering | 12.2659초 |
| total | 14.9713초 |

관찰된 가장 큰 병목은 clip rendering이었다. 이 검증에서는 FFmpeg 설정이나 성능을 변경하지 않았다.

## 14. 브라우저 체감 시간

처리 버튼 클릭부터 결과 화면 표시까지 약 28.2초가 관찰되었다. Pipeline total과의 차이에는 업로드, Streamlit rerun, HTTP 응답 변환, clip 다운로드와 화면 렌더링이 포함된다. 이 수치는 성능 benchmark가 아니다.

## 15. 보안 확인

브라우저 UI와 API 응답에서 다음 정보가 노출되지 않음을 확인했다.

- 로컬 절대 경로
- `source_path` / `clip_path` / WAV 경로
- `outputs/` 내부 경로
- API key 및 `.env` 값
- traceback

Frontend는 backend가 제공한 상대 `download_url`로만 MP4를 받았다.

## 16. 현재 MVP 제약

- Window는 5·10·15·30초 중 사용자가 수동으로 선택한다.
- 요청은 동기적으로 대기하며 세부 progress, SSE, WebSocket은 없다.
- Pipeline 동시 실행은 한 개로 제한된다.
- upload source와 생성 clip은 로컬 파일 시스템에 보존되며 자동 보존 기간 정책은 없다.
- 인증, DB, object storage, background queue는 구현되지 않았다.
- clip rendering이 이 실행의 주요 병목이었다.

## 17. 이번 검증에서 확인한 것

- 실제 브라우저에서 upload, Window 선택, process 시작이 가능했다.
- Streamlit → FastAPI → VideoProcessingPipeline 흐름이 성공했다.
- Transcript, EditMemo, Candidate, Selection이 UI에 표시되었다.
- 생성 MP4가 clip endpoint를 통해 전달되어 브라우저에서 재생되었다.
- 자동 retry 없이 process POST 1회로 완료되었다.
- intermediate WAV cleanup과 source/final clip 보존 정책이 작동했다.

## 18. 이번 검증에서 확인하지 않은 것

- 장면 선택 정확도나 자동 Window 선택 품질
- 긴 영상과 다양한 codec/container의 처리 한계
- 다중 사용자, 동시 요청, queue 대기 UX
- 복수 EditMemo와 각 오류 상태의 실제 브라우저 UX
- 모바일 브라우저 호환성
- 인증, 배포, cloud storage, 보존 기간 정책
- rendering 성능 최적화
