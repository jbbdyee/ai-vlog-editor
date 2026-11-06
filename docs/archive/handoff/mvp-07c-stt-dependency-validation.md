# MVP-07C — STT 의존성 호환성 및 Windows 재설치 검증

검증 기준 커밋: `main` / `629b198517c845762c2ceea787c5e733035d8183`, 2026-10-24. 이 문서는 [MVP-07B 원인 분석](mvp-07b-root-cause-analysis.md)의 STT 문제를 수정·검증한 후속 기록이다. 앞선 실제 영상 전체 흐름의 결과는 [MVP-07A](mvp-07a-real-video-validation.md)를 따른다. 이번 변경은 `requirements.txt`의 PyAV 한 줄뿐이며 제품 코드, 평가 계약·GT·Manifest, 원본 영상, 기존 렌더 산출물은 수정하지 않았다.

## 현상과 원인

수정 전 Windows `.venv`는 Python 3.12.15, `faster-whisper==1.2.1`, `av==19.0.2`였다. 같은 P1-S01에서 추출한 실제 WAV를 `transcribe_audio(..., word_timestamps=True)`로 다시 실행하면 아래 호출에서 실패했다. `stt_service.py`는 원인 예외를 `STTError`로 감싼다.

```text
backend/app/services/stt_service.py:77        stt_model.transcribe(...)
faster_whisper/transcribe.py:876               decode_audio(...)
faster_whisper/audio.py:46                     av.open(..., metadata_errors="ignore")
av/container/core.py:479                      TypeError: open() got an unexpected keyword argument 'metadata_errors'
backend/app/services/stt_service.py:89        STTError: STT transcription failed for <WAV>.
```

기존 `requirements.txt`는 faster-whisper만 직접 고정했고 PyAV 선언이나 lock 파일은 없다. faster-whisper 1.2.1의 패키지 요구 조건은 `av>=11`이라 av 19.0.2 설치를 막지 못한다. [PyAV 19 릴리스](https://github.com/PyAV-Org/PyAV/releases)에서 해당 인자가 제거됐고 [faster-whisper 이슈](https://github.com/SYSTRAN/faster-whisper/issues/1589)에 같은 호환성 문제가 보고됐다. 07A/07B에서 별도 격리한 av 18.1.0으로 같은 실제 WAV 전사가 성공했던 것도 재현 근거다.

## 선택과 대안

`requirements.txt`에 `av==18.1.0`을 명시했다. 이미 P1-S01 실제 입력에서 성공한 정확한 조합을 깨끗한 설치에서 다시 확인할 수 있고, 제품 STT 코드를 바꾸지 않는다. `av>=11,<19`는 av 19 문제를 피하면서 호환되는 마이너 업데이트를 허용하지만 설치 시점에 선택되는 버전이 달라져 이번 실험과 동일한 환경을 보장하지 않는다. 고정은 PyAV의 보안·기능 업데이트를 자동 반영하지 않으므로 후속 검토가 필요하다.

faster-whisper의 [정식 릴리스](https://github.com/SYSTRAN/faster-whisper/releases)는 조사 시점에 1.2.1이 최신이었다. 개발 브랜치의 PyAV 19 대응 코드를 정식 배포의 동작으로 간주하지 않았다. 정식 호환 릴리스가 나오면 별도 가상환경에서 두 패키지 조합, 실제 WAV, 소스 처리 회귀를 검증한 뒤 고정 버전을 갱신한다. 이번에는 다른 패키지를 직접 업그레이드하지 않았다. 다만 lock 파일이 없으므로 전체 전이 의존성은 시점에 따라 달라질 수 있다. 지원 OS별 설치 검증과 lock/constraints 관리 방식을 추후 결정해야 한다.

## 깨끗한 Windows 환경 설치

저장소의 무시되는 `evaluation/tmp/mvp-07c-clean-venv/`에 Python 3.12.15 가상환경을 새로 만들었다. `pyvenv.cfg`의 `include-system-site-packages = false`를 확인했다. 설치는 `python -m pip install -r requirements.txt`로 수행했다. 최초 sandbox 네트워크 제한 때문에 PyPI 접근이 거부됐고, 허용된 네트워크 실행으로 동일 명령을 다시 실행해 성공했다. 설치된 핵심 버전은 faster-whisper 1.2.1 / av 18.1.0이다. `python -m pip check`는 `No broken requirements found.`로 종료했다. 기존 `.venv`나 `.env`는 변경하지 않았다.

재현 명령(PowerShell; 새 가상환경 경로를 사용):

```powershell
python -m venv evaluation/tmp/mvp-07c-clean-venv
evaluation/tmp/mvp-07c-clean-venv/Scripts/python.exe -m pip install -r requirements.txt
evaluation/tmp/mvp-07c-clean-venv/Scripts/python.exe -m pip check
```

실제 WAV 디코딩 확인(07A의 로컬 추출 WAV가 있는 경우):

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
evaluation/tmp/mvp-07c-clean-venv/Scripts/python.exe -c "from backend.app.services.stt_service import load_model,transcribe_audio; p='evaluation/tmp/mvp-07a-p1-s01-20261024-013830-247a62bc/77c53379e8904b338cad0fcb25d6bec5.wav'; r=transcribe_audio(p,model=load_model(),word_timestamps=True); print(r.text, len(r.segments), [len(s.words) for s in r.segments])"
```

모델은 로컬 캐시의 `small` / CPU `int8`로 실행했다. 실행 프로세스 안에서 `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`을 설정하고 외부 LLM/VLM 키를 빈 값으로 가렸다. 외부 LLM/VLM API 호출은 없다. 네트워크는 패키지 설치에만 사용했다.

## 실제 WAV 및 P1-S01 소스 처리

- 입력 WAV: 07A의 격리 출력 디렉터리에 보관된 P1-S01 추출 오디오. 새 환경의 `load_model()` 약 1.16초, `transcribe_audio(..., word_timestamps=True)` 약 6.45초. 언어 `ko`, 전사 `아 뭐야 에이아이아 방금 장면 살려줘`, segment 2개(4.64~6.12초, 8.44~11.00초), 단어 시각 6개를 확인했다. 문구와 시각은 07B 저장 전사 비교와 일치한다. 이 결과는 호환성 검증이며 STT 인식 품질 합격 판정은 아니다.
- 원본: `evaluation/data/P1/P1_S01_take01.MOV`, SHA-256 `205e4143822520183d446c154fc314f607b3c948ec2e264b37195933d89a01d2`. 새 격리 프로젝트 `c93e6b33-2d89-4050-afac-63af160afbd7`에 API로 등록했으며 등록 사본 SHA-256이 원본과 같음을 확인했다. 기존 프로젝트·렌더는 사용하거나 수정하지 않았다.
- `POST /projects/{id}/process`는 202를 반환했다. 후속 `GET /projects/{id}/processing`은 200, 프로젝트 `COMPLETED`, source 1개 완료·실패 0개·남은 항목 0개였다. DB에서 `PROBE`, `AUDIO_EXTRACTION`, `STT`, `MEMO_DETECTION` 네 단계가 모두 `COMPLETED`, 오류 코드 없음, 전사 2개 segment와 6개 단어가 저장됐음을 확인했다. 없는 프로젝트의 처리 조회는 404였다. 실제 소스 처리에는 FFmpeg를 기존 로컬 설치에서 제공했다. SceneCandidate·렌더·자막은 이번 회귀 범위에서 재실행하지 않았다.
- 일회성 검증 스크립트는 처리 상태 응답에 없는 `run_status`를 읽어 `KeyError`로 종료했다. 이는 스크립트의 필드명 오류다. 앱 종료 시 백그라운드 처리는 완료됐으며, 새 세션에서 위 API·DB 상태를 재조회했다. 이 오류 때문에 해당 스크립트의 단계별 소요 시간은 남지 않았다. 실행 명령 전체는 약 10.12초였으나 이를 순수 처리 시간으로 해석하지 않는다. 일회성 스크립트와 가상환경은 Git 무시 경로에만 있다.

## 회귀 테스트 및 영향

깨끗한 환경에서 `python -m unittest -v backend.tests.test_stt_service backend.tests.test_source_processing backend.tests.test_source_ingestion backend.tests.test_video_process_api backend.tests.test_project_processing` 실행 결과 55건 통과, 이어 `python -m unittest -v backend.tests.test_project_api` 10건 통과였다. **합계 65건 통과, 실패 0, 건너뜀 0**이다. 정상 전사·소스 처리와 빈/비 WAV 입력, 모델 로드·디코드·지연 iterator 실패, STT 실패 시 전사 미저장, 재시도·복구, 프로젝트·영상 API 성공·404·422·415·500 경로를 포함한다. 이 중 대부분은 mock 기반 단위/API 테스트다. 위 실제 WAV 및 P1-S01 처리가 실제 디코더 검증을 보완한다.

커밋 전 최종 점검에서 기존 Windows `.venv`에도 `python -m pip install -r requirements.txt`를 적용했다. av 19.0.2가 18.1.0으로 교체됐고 faster-whisper는 1.2.1 그대로였다. 그 환경의 `pip check`는 `No broken requirements found.`였으며 같은 실제 WAV의 전사 segment 2개와 단어 시각 6개가 정상 반환됐다.

의존성 선언 변경은 STT 디코딩과 그 뒤의 전사·메모·Scene Evidence·자막 입력에 영향을 줄 수 있다. 제품 알고리즘이나 렌더 코드 자체는 바꾸지 않았다. 다른 운영체제, 장시간·다른 코덱 소스, 전체 렌더/Streamlit 사용자 조작, 추천 정량 품질은 이번에 실행하지 않았다. 다른 기존 설치·배포 환경은 새 requirements를 적용해야 한다.
