# Cutory MVP-06C-2A 인수인계 — Mac → Windows/WSL/Docker

> 기준: `jbbdyee/ai-vlog-editor` 원격 `main`의 `75f479adf47c636e3b10da47bd90900c09ca54e1` (2026-10-22 확인). 이 문서는 그 시점의 코드와 사용자가 제공한 06C-2A 실행 기록을 구분한다. 이 문서 추가 외 서비스 코드·설정·평가 계약은 변경하지 않았다.

## 1. 먼저 알아야 할 상태

| 범위 | 구현 및 검증 상태 |
| --- | --- |
| v1 | Project/Source 저장, 처리 상태, 재개·부분 실패 기반 완료. 근거: `docs/roadmap/v1-completion.md`, `evaluation/results/cutory-v1-foundation-eval-v0.1.md`. |
| v2 | Scene Intelligence 구조/기반 구현 후 Gap Closure 진행 중. 전체 완료 아님. G1 실제 Text LLM 평가는 API key 부재로 차단, G2/G3 보류, G5의 실제 media/GT freeze 미완료. `AGENTS.md`와 `docs/roadmap/v2-plan.md` 우선. |
| MVP-05A/B/C | 저장된 Scene 편집 계획을 H.264/AAC MP4로 렌더링하고 API/Streamlit에서 실행·다운로드. 합성 미디어 중심 검증. 렌더 상태·완료 ID는 프로세스 메모리 전용. |
| MVP-06B | 저장된 Transcript와 선택 구간에서 SRT 문자열을 만드는 순수 로직. |
| MVP-06C-1 | MP4 렌더의 30fps 정규화 시간축을 측정해 `final.srt`를 `final.mp4` 옆에 저장. 클립 요청 길이와 출력 길이는 비례 매핑. 시간축 불일치·SRT 생성 실패 시 MP4는 유지하고 SRT는 생략. 기존 MP4 다운로드 API는 그대로. |
| MVP-06C-2A | **서비스 코드 변경 없음.** Mac의 일회성 격리 Docker 환경에서 별도 합성 영상에 한국어 하드 자막을 입히는 기술 검증만 완료. 제품 렌더 경로와 연결되지 않음. |

확인할 코드: `backend/app/services/project_subtitles.py` (cue/SRT), `backend/app/services/project_rendering.py` (렌더·시간축·`final.srt`), `backend/app/services/project_render_execution.py` (프로세스 내 상태), `backend/tests/test_project_subtitles.py`, `backend/tests/test_project_rendering.py`, `backend/tests/test_project_render_api.py`. 현재 서비스에는 SRT 다운로드나 MP4 하드 자막 경로가 없다.

## 2. 06C-2A의 증거와 경계

아래는 이전 Mac 작업의 **사용자 제공 검증 기록**이다. 이 인수인계 작업에서 Docker 렌더를 다시 실행하거나 원본 로그·파일을 재검증하지 않았다.

- LinuxServer FFmpeg의 **linux/arm64** 이미지 digest: `sha256:2fa8c91f8ade9d050a29c9f64405f2c752df6616c4f3b986974685b896b0fe2c`. 컨테이너 FFmpeg 9.0.2에서 libass 및 `subtitles`/`ass` 필터 확인. [이미지 프로젝트](https://github.com/linuxserver/docker-ffmpeg).
- macOS 시스템 FFmpeg 9.0.1에는 두 자막 필터가 없었고 교체하지 않았다.
- 공식 `NotoSansCJKkr-Regular.otf` SHA-256: `6bcb2a0703aa137e874fc2dffa85f6c21ba9a67fa329e81b8c801663af7e992a`. [공식 파일](https://github.com/notofonts/noto-cjk/blob/main/Sans/OTF/Korean/NotoSansCJKkr-Regular.otf), [SIL OFL 1.1](https://github.com/notofonts/noto-cjk/blob/main/Sans/LICENSE). 렌더 로그에서 글꼴 선택 확인.
- 5초 합성 MP4 + 한국어 SRT로 하드 자막 MP4 생성. 0.5·2.5·4.5초에는 자막 없음, 1.5·3.5초에는 한국어 및 `&` 표시. FFprobe 결과 1280×720, 30fps, H.264/AAC, 5.000초.
- 네트워크 없는 일회성 실행 컨테이너에 Docker socket, 홈, 저장소, 사용자 영상, DB를 마운트하지 않았다. 임시 영상·SRT·프레임·글꼴 복사본과 컨테이너는 삭제했고 이미지만 캐시에 남겼다.
- 폰트 캐시 쓰기 불가 및 libass Unicode 자동 줄바꿈 경고가 있었다. 짧은 검증 자막에는 영향이 없었으나 긴 문장, 다중 행, 실제 편집 영상의 동기화는 미검증이다. 이미지 배포 라이선스도 제품 배포 전 확인해야 한다.

**Digest 주의:** 위 digest는 Mac에서 확인한 arm64 이미지의 증거다. Windows PC의 Docker가 `linux/amd64`이면 같은 문자열을 그 플랫폼의 검증된 이미지로 취급하지 않는다. 사용 전 해당 플랫폼의 manifest/platform, 실제 pull 결과 digest, FFmpeg 버전·libass·필터를 다시 기록한다. Noto 파일도 내려받은 바이트의 SHA-256을 확인한다.

## 3. Windows PC로 옮긴 직후 실행 순서

1. Windows에서 Git, Python, Docker Desktop과 WSL2 백엔드를 준비한다. Docker Desktop이 Linux containers 모드인지 확인한다. 저장소는 가능하면 WSL 파일시스템 안에 clone하고 WSL 터미널에서 작업한다. Windows PowerShell 작업을 택하면 경로와 가상환경 활성화 명령을 그 환경에 맞춘다.
2. 원격 상태를 확인하고 기준 커밋 및 깨끗한 작업 트리를 기록한다.

   ```bash
   git clone https://github.com/jbbdyee/ai-vlog-editor.git
   cd ai-vlog-editor
   git fetch origin
   git status --short --branch
   git log -1 --format='%H %s'
   git diff --name-only
   ```

   이 문서 커밋 후에는 HEAD가 `75f479a`보다 앞선다. 문서 커밋을 제외한 서비스 변경이 없는지 `git diff 75f479adf47c636e3b10da47bd90900c09ca54e1 --name-only`로 확인한다. 이후 누군가 변경했다면 새 HEAD를 재평가한다.

3. `AGENTS.md`, `README.md`, `docs/roadmap/v2-plan.md`, 이 문서를 읽는다. `.env.example`을 로컬 `.env`로 복사하고 `POSTGRES_PASSWORD`를 로컬 값으로 정한다. `.env`와 원본 media는 Git에 넣지 않는다.
4. Python 가상환경과 의존성을 준비한다. WSL 예시:

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   docker compose up -d postgres
   .venv/bin/python -m alembic upgrade head
   .venv/bin/python -m unittest backend.tests.test_project_subtitles backend.tests.test_project_rendering backend.tests.test_project_render_api -v
   ```

   PowerShell이면 `py -m venv .venv`, `.\.venv\Scripts\python.exe`을 사용한다. 설치 전 Python/패키지의 Windows 호환성, FFmpeg/FFprobe 경로와 Docker 상태를 확인한다. DB는 기존 사용자 데이터가 있으면 초기화하거나 볼륨을 삭제하지 않는다.

5. 호스트의 `ffmpeg -version`, `ffprobe -version`, `ffmpeg -filters`에서 `subtitles`/`ass` 지원을 확인한다. 이는 **기존 호스트 도구 조사**다. 06C-2B에서 컨테이너 렌더러를 택했다면 별도로 PC의 `docker version`, `docker info`, `docker image inspect`, 컨테이너 안 `ffmpeg -version` 및 필터를 기록한다. amd64 이미지 확인 전 arm64 digest를 실행 지침에 고정하지 않는다.
6. 공식 글꼴과 라이선스를 별도 작업 폴더로 받아 SHA-256을 검증한다. `sha256sum NotoSansCJKkr-Regular.otf`의 결과가 위 값과 다르면 사용하지 않는다. 제품에 포함할지, 런타임 자산으로 받을지는 06C-2B에서 배포·라이선스 정책과 함께 결정한다.
7. 우선 합성 영상·SRT로 호스트별 격리 렌더를 반복하고 프레임 전·중·후, 한글/특수문자, ffprobe의 해상도·fps·코덱·길이를 확인한다. 이어 실제 제품 `final.srt`와 `final.mp4` 복사본으로 짧은·긴·다중 행 자막 및 여러 클립 경계의 동기화를 검증한다. 원본 media/DB/저장소를 컨테이너에 직접 쓰기 마운트하지 않는다. 개인 영상은 승인된 로컬 위치에서만 다룬다.

`README.md`의 API 실행은 `python -m uvicorn backend.app.main:app --reload`, 화면은 `python -m streamlit run frontend/app.py`다. 프로젝트 DB 기능을 쓰려면 DB 연결 및 migration을 먼저 확인한다. API와 화면은 로컬 개발용이며 사용자별 인증은 아직 없다.

## 4. 다음 작업: MVP-06C-2B 이후

### 06C-2B — 제품 렌더 연결

- 컨테이너 실행 파일/이미지 **플랫폼별 digest**, 글꼴 바이트·OFL 고지, 실행 환경과 실패 코드의 계약을 먼저 문서화한다. Docker 사용 시 사용자 홈·Docker socket·DB·원본 저장소 전체를 넘기지 않는 최소 입력/출력 경계를 설계한다. Windows/WSL 경로 매핑, 권한, 시간 제한, 리소스 한도도 검증한다.
- 기존 `final.mp4` + `final.srt`를 입력으로 하드 자막 결과를 **별도 임시 파일**에 만든다. 렌더 명령은 shell 문자열 연결 대신 인자 배열과 안전한 경로 처리를 사용한다. 한국어 글꼴을 명시하고 libass 필터 존재를 시작 전 확인한다.
- 임시 결과가 존재하고 비어 있지 않은지, ffprobe가 영상/오디오 스트림과 예상 길이·코덱을 확인하는지 검사한다. 자막 프레임을 직접 확인한 뒤 성공할 때만 결과에 반영한다. 실패 시 기존 MP4/SRT를 보존하고 안전한 오류를 반환한다. 파일 덮어쓰기·실패 후 부분 결과 노출을 막는다.
- 무자막, 빈 SRT, 글꼴 없음, 필터 없음, 경로 특수문자, 한글·`&`, 여러 줄, 클립 경계, 실제 영상과 장시간 작업을 정상/실패 경로로 검증한다. 렌더 상태가 메모리 전용이라는 기존 한계도 유지하거나 별도 설계 변경으로 명시한다.

### 후속 범위

- 하드 자막 다운로드/선택 UX와 원본 MP4·SRT·하드 자막 결과의 구분은 API/화면 계약을 정한 뒤 구현한다. 현 다운로드 API가 이미 하드 자막을 제공한다고 표시하지 않는다.
- 실제 촬영 영상 E2E, 긴 문장 줄바꿈/가독성, 다중 클립 오디오·PTS 동기화, 반복 실행과 Windows/WSL 성능을 평가한다. 합성 5초 성공만으로 제품 품질을 선언하지 않는다.
- 이미지·폰트 재배포 조건과 라이선스 파일 동봉 방식을 결정한다. 외부 모델·새 운영 의존성은 목적, 비용, 개인정보 영향 및 평가 근거를 남긴다.

## 5. 변경 금지선과 다음 작업자에게 전달할 지시

이번 인수인계는 자막 렌더의 제품 연결을 위한 것이다. P1~P3 평가 계약, Ground Truth, Manifest, `SceneCandidate`, STT/VAD, Visual 임계값, DB schema/migration, API 계약은 근거 없는 편의 변경을 하지 않는다. 필요한 변경이 드러나면 원래 문서·테스트·평가 기준을 대조하고 별도 제안과 검증으로 분리한다. `evaluation/data/`의 실제 media, `.env`, DB dump, 글꼴 임시 복사본을 커밋하지 않는다.

다음 Codex는 **원격 HEAD와 환경을 재확인**한 뒤 06C-2B의 설계·격리 검증부터 진행한다. arm64 검증값을 amd64 성공 증거로 인용하지 말고, 제품 코드가 이미 하드 자막을 지원한다고 기록하지 않는다.
