# MVP-07A 실제 촬영 영상 통합 검증

검증일: 2026-10-24 (Asia/Seoul)

기준: `main` / `b9ffb25ed2d2cf6d227d667084fbfaeaa40ec8b0`

범위: P1-S01 한 건의 로컬 API 수준 통합 실행. 제품 코드, 원본 영상, Manifest, GT, 평가 계약은 수정하지 않았다. 커밋과 Push는 하지 않았다.

## 대상과 실행 격리

- 실제 입력: `evaluation/data/P1/P1_S01_take01.MOV` (141,327,567바이트, SHA-256 `205e4143822520183d446c154fc314f607b3c948ec2e264b37195933d89a01d2`). P1-S01 초안에 기재된 해시와 일치한다.
- 입력 FFprobe: 13.498333초, HEVC 3840×2160 60fps 영상 + AAC 오디오.
- 성공 실행 기록: `evaluation/tmp/mvp-07a-p1-s01-20261024-014109-1716ba7c/run.json` (Git 제외 경로). 새 프로젝트 `73b0df34-1dd7-4d4e-a532-8cc7b623e4bc`, 소스 `741a67b7-8d6b-44a8-8c5e-e023ec6991a5`, 렌더 `a6803979-a02a-4ee1-ab8a-d134b43c4c06`.
- 원본을 새 프로젝트의 `storage/originals/projects/73b0df341dd74d4ea5328cc7b623e4bc/sources/b10a4a4a525a4681a6ea6ea60e0871dc.mov`에 등록했다. 등록본의 SHA-256은 입력과 같다. 기존 프로젝트와 렌더를 재사용하거나 덮어쓰지 않았다.
- 첫 실패 실행도 별도 프로젝트 `da96630e-5356-4ffe-8ac3-c5f0ea1ec9bc` 및 `evaluation/tmp/mvp-07a-p1-s01-20261024-013830-247a62bc/run.json`에 보존했다. 두 실행과 진단 파일은 저장 공간을 사용하지만 삭제하지 않았다.

## 환경 확인

| 항목 | 관찰 결과 |
| --- | --- |
| Docker | Docker Desktop CLI와 Linux 엔진 모두 실행됨. 양쪽 버전 29.9.2. 로컬 FFmpeg 이미지가 있으며 네트워크를 끈 컨테이너에서 `ass`, `subtitles` 필터 확인. |
| 호스트 FFmpeg | 번들 FFmpeg/FFprobe 9.0.2 실행됨. `ass`, `subtitles` 필터 확인. |
| 글꼴 | `evaluation/tmp/subtitle-font/NotoSansCJKkr-Regular.otf`, SHA-256 `6bcb2a0703aa137e874fc2dffa85f6c21ba9a67fa329e81b8c801663af7e992a`. 실행 프로세스에만 `CUTORY_SUBTITLE_FONT_PATH` 지정. |
| 서비스 | PostgreSQL 5432 연결됨; Alembic `ca3e4f5a6b7c (head)`. API 8000/Streamlit 8501 상주 서버는 없어서 FastAPI `TestClient`로 API를 실행. |
| 저장 공간 | 실행 전 C: 여유 약 733.2GB (682.8GiB). 입력 141.3MB를 실행별 프로젝트에 복사하므로 최소 수백 MB의 추가 사용을 예상했다. 성공 산출물 MP4 두 개는 합계 약 90KB. |
| 외부 호출 | 프로세스 범위에서 `OPENAI_API_KEY`, `GEMINI_API_KEY`를 빈 값으로 가리고 Hugging Face/Transformers 오프라인 설정을 적용했다. 결정적 `/scene-process` 경로를 사용했으며 외부 LLM/VLM 요청을 실행하지 않았다. 기존 `.env`는 수정하지 않았다. 외부 API 비용 0. |

## 단계별 결과

시간은 성공 실행의 실제 경과 시간이다. 포함된 하위 작업의 독립 소요 시간은 따로 측정하지 않았다.

| 단계 | 결과 | 시간 | 확인 내용 |
| --- | --- | ---: | --- |
| 사전 확인/API 시작 | 성공 | 0.109초 / 1.141초 | 입력·글꼴 해시, FFprobe 및 앱 시작 확인. |
| 영상 등록·메타데이터 | 성공 | 0.593초 | 새 프로젝트/소스 생성, 복사본 해시 일치. 소스 처리 PROBE 완료. DB 메타데이터의 길이 13.498초와 코덱은 채워졌으나 width/height/fps는 `null`; 원본 FFprobe에는 값이 있다. |
| 오디오 추출·STT·메모 단계 | 성공(호환 PyAV 한정) | 8.063초 | 처리 상태 `COMPLETED`, 1개 소스 완료, AUDIO_EXTRACTION/STT/MEMO_DETECTION 완료. 실제 한국어 전사 2개 구간 생성. 메모 검출의 내용·정확도는 별도 확인하지 않았다. |
| 오디오·영상 Evidence 및 SceneCandidate | 생성 성공 | 6.078초 | scene run `COMPLETED`, 후보 5개. 진단에는 TRANSCRIPT 2, AUDIO 20, VISUAL 2, QUALITY 1개 Evidence 기록. 추천 품질 합격 판정은 하지 않았다. |
| 장면 선택·편집 계획 | 성공(검증자 선택) | 0.015초 | 촬영자 확인 구간 4.00~6.22초와 겹치는 후보 가운데 겹침이 가장 긴 5.54~6.12초 후보 1개를 선택. 이 선택은 자동 추천 품질을 증명하지 않는다. |
| 최종 렌더 | 파일·재생 정보 확인 | 4.078초 | 렌더 상태 `COMPLETED`, `final.mp4` 파일 존재·FFprobe 성공·프레임 디코딩 성공. |
| SRT | 파일·내용 확인 | 0.000초(검사만) | `final.srt`에 1개 cue. 생성은 렌더 단계에 포함. |
| 한국어 하드 자막 | 파일·프레임 확인 | 0.032초(검사만) | `final-subtitled.mp4` 존재·FFprobe 성공. 0.3초 프레임에서 한글 자막 표시 확인. 자막 인코딩은 렌더 단계에 포함. |
| 기본/자막 MP4 API 조회·다운로드 | 성공 | 0.031초 | 렌더 조회에서 두 다운로드 가능 상태. 양쪽 HTTP 200, `video/mp4`, 지정된 파일명 확인. 응답 SHA-256이 각 산출물과 일치. |

### 전사와 후보 근거

전체 전사: `아 뭐야 에이아이아 방금 장면 살려줘` (언어 `ko`). 첫 구간 4.64~6.12초 `아 뭐야`, 두 번째 8.44~11.00초 `에이아이아 방금 장면 살려줘`. 기존 촬영자 검토 기록은 반응을 `어 뭐야`로 적고 있어 첫 음절에 명백한 차이가 있다. 반응 구간은 모델의 첫 단어 확률도 약 0.29로 낮다. 메모 구간은 기존 로컬 관찰과 대체로 맞지만 독립적인 정답 대조는 수행하지 않았다.

| 후보 구간(초) | 생성 근거 |
| --- | --- |
| 2.44~2.62 | AUDIO_ACTIVITY, VISUAL_ACTIVITY |
| 4.08~4.60 | AUDIO_ACTIVITY, VISUAL_ACTIVITY |
| 4.64~4.84 | AUDIO_ACTIVITY, STATIC_INTERVAL, TRANSCRIPT_STRUCTURE |
| **5.54~6.12 (선택)** | AUDIO_ACTIVITY, STATIC_INTERVAL, TRANSCRIPT_STRUCTURE |
| 8.86~11.00 | AUDIO_ACTIVITY, STATIC_INTERVAL, TRANSCRIPT_STRUCTURE |

초안의 촬영자 확인 사건 구간은 4.00~6.22초이다. 선택 구간 5.54~6.12초는 그 일부만 담는다. 따라서 후보 생성 성공과 사건 전체 포착·좋은 편집 선택은 구분해야 한다. GT가 동결되지 않았으므로 정량 품질 합격이나 IoU 합격은 선언하지 않는다. 특히 8.86~11.00초 후보는 나중에 발화한 AI 메모와 겹친다.

### 산출물과 내용 검증

산출물 공통 디렉터리: `outputs/projects/projects/73b0df341dd74d4ea5328cc7b623e4bc/renders/a6803979a02a4ee1ab8ad134b43c4c06/`.

| 파일 | FFprobe·파일 결과 | SHA-256 |
| --- | --- | --- |
| `final.mp4` | 0.583333초, H.264 1280×720 30fps + AAC, 44,492바이트 | `5ca3366e19dd0ee86002ca85b1c13501f6ba9ef87ac61cd767dfbe45cb1e64e1` |
| `final.srt` | 45바이트, cue `00:00:00,000 --> 00:00:00,566`, 텍스트 `아뭐야` | `709fa736d1f70743f676b0536bb2dc61811f3493e9e38f33fca2a7eef05ad850` |
| `final-subtitled.mp4` | 0.583333초, H.264 1280×720 30fps + AAC, 45,819바이트 | `088f3d14240acac019a8c89c1d73d22a77ff9b4300c04a40b5886ecea62fd886` |

SRT의 `아뭐야`는 실제 전사 `아 뭐야`에서 공백이 사라졌고 촬영자 기록의 `어 뭐야`와 첫 음절이 다르다. 다만 cue 0~0.566초는 선택한 5.54~6.12초 구간 안의 발화 시점과 대체로 맞는다. 프레임 비교 파일은 성공 실행의 `plain-frame.png`, `subtitled-frame.png`에 격리했다. 0.3초 프레임에서 기본 MP4에는 자막이 없고 자막 MP4에는 `아뭐야`가 한글로 표시된다. 단일 프레임 확인이므로 전체 자막 품질 판정은 아니다.

렌더 조회는 `succeeded=true`, `hard_subtitle_status=AVAILABLE`, 두 다운로드 가능 상태였다. 기본 다운로드 응답은 `inline; filename="a6803979a02a4ee1ab8ad134b43c4c06.mp4"`, 자막 응답은 `attachment; filename="a6803979a02a4ee1ab8ad134b43c4c06-subtitled.mp4"`; 양쪽 `Content-Type: video/mp4`이며 각각 44,492/45,819바이트와 산출물 SHA-256이 일치했다. 이는 로컬 TestClient를 통한 API 검증이다. Streamlit 화면에서 사용자가 버튼을 클릭하는 검증은 건너뛰었다.

## 오류, 제한 및 우선순위

1. **P0 — STT 의존성 호환성.** 기본 설치 `faster-whisper 1.2.1` + `av 19.0.2`로 첫 실행 시 PROBE와 오디오 추출 후 STT가 `STT_FAILED`가 됐다(2.047초). 같은 추출 WAV로 재현하면 `TypeError: open() got an unexpected keyword argument 'metadata_errors'`. `av 18.1.0`을 `evaluation/tmp/.../python-packages`에 별도로 설치해 이번 프로세스의 `PYTHONPATH`에만 우선 적용하자 성공했다. 제품 의존성은 변경하지 않았다. 일반 설치 상태에서 재실행하면 재발할 수 있으므로 호환 버전 정책 검토가 필요하다. 관련 업스트림: <https://github.com/SYSTRAN/faster-whisper/issues/1589>.
2. **P1 — 편집 구간 품질.** 후보 5개가 생성됐지만 검증자가 선택한 최대 겹침 후보는 0.58초로 촬영자 확인 사건 2.22초 중 일부에 불과하다. 선택 장면 프레임에는 리모컨이 매트 위에 보이며, 물체가 떨어지는 전체 흐름을 포괄하는지 확인되지 않는다. GT freeze 후 후보 recall, 경계와 편집 선택 품질을 별도 평가해야 한다.
3. **P2 — 전사·자막 정확도.** 촬영자 기록 `어 뭐야`에 비해 STT `아 뭐야`, SRT `아뭐야`다. 첫 음절 및 공백 처리 경로를 재검토할 필요가 있다. 현재 성공은 파일 생성·표시 검증이며 내용 정확도 합격은 아니다.
4. **P3 — 메타데이터와 UI 검증.** DB 소스 width/height/fps가 비어 있으나 FFprobe 원본과 결과에는 값이 있다. 메타데이터 저장 경로 확인이 필요하다. 상주 서버/Streamlit 사용자 조작, 전체 자막 프레임, 메모 인식 정확도, P2·P3 영상, `IMG_6256/6257`, 다른 프로젝트 영상은 이번 범위에서 검증하지 않았다. 건너뛴 항목은 통과로 집계하지 않는다.

시작 시 존재한 미커밋 변경 `backend/tests/test_clip_download_api.py`, `backend/tests/test_project_render_api.py`, `backend/tests/test_project_rendering.py`는 건드리지 않았고 마지막 확인에서도 동일한 세 파일만 수정 상태였다(이 보고서 작성 전). 새로운 검증 스크립트·실행 로그·프레임·복사본·렌더 파일은 Git 제외 경로에 격리했다. 기존 평가 문서와 원본 미디어는 수정하지 않았다.

후속 STT 의존성·SceneCandidate 구간·SRT 공백 문제의 원인 분석은 [MVP-07B 기록](mvp-07b-root-cause-analysis.md)을 참고한다. 이 링크는 위 실행 결과와 당시 검증 범위를 변경하지 않는다.
