# MVP-06C-2B Windows 합성 미디어 검증

## 환경과 입력 경계

- Windows 11, WSL2 Ubuntu 24.04, Docker Desktop Linux 엔진 `linux/amd64`, Python 3.12.15 가상환경, PostgreSQL 17.11 기존 볼륨에서 작업했다.
- Docker FFmpeg 9.0.2 이미지의 amd64 manifest는 `lscr.io/linuxserver/ffmpeg@sha256:1f9755c920d41b30c4630eb6d54ac4d9badc4f5b0ca3e7f495a98d00e8020c3a`이다. 인수인계에 기록된 arm64 digest는 사용하지 않았다. 컨테이너에서 `ass`와 `subtitles` 필터를 확인했다.
- 공식 NotoSansCJKkr-Regular.otf의 SHA-256은 `6bcb2a0703aa137e874fc2dffa85f6c21ba9a67fa329e81b8c801663af7e992a`로 확인했다. 글꼴은 배포물에 넣지 않고 로컬 `CUTORY_SUBTITLE_FONT_PATH`로 지정한다. 재배포 전 SIL OFL 고지 방식과 Docker 이미지 라이선스를 별도로 확정해야 한다.
- Docker 실행에는 합성 또는 렌더 완료된 MP4/SRT와 글꼴의 **복사본만** 있는 임시 디렉터리를 마운트한다. 네트워크를 끄고 CPU·메모리·프로세스 제한을 둔다. Docker socket, DB, 원본 저장소 전체를 마운트하지 않는다. 실행 시간 상한은 1800초다.

## 동작과 검증 범위

- 기존 프로젝트 렌더가 `final.mp4`와 `final.srt`를 만들고, 환경 변수 `CUTORY_SUBTITLE_FONT_PATH`가 설정되면 별도 `final-subtitled.mp4`를 생성한다. 기존 MP4/SRT는 덮어쓰지 않는다. 무자막이면 하드 자막 렌더를 건너뛴다.
- 컨테이너는 H.264 비디오를 다시 인코딩하고 AAC 오디오는 복사한다. 출력 파일 크기, 영상/오디오 스트림, H.264/AAC 코덱, 원본 대비 길이 오차 0.1초 이하를 검사한 뒤 결과를 게시한다. 실패는 `hard_subtitle_error_code`에 안전한 코드로 남기고 기본 MP4/SRT를 보존한다.
- 합성 4초 MP4와 두 큐의 한국어·`&`·두 줄 SRT를 사용해 0.5·3.5초에는 자막이 없고 1.5·2.5초에는 자막이 있음을 프레임 밝기 차이로 검사했다. SRT 비어 있음, 글꼴 누락, 한글/특수문자 경로와 기본 파일 보존도 검증했다.
- 전체 백엔드 회귀 테스트: `RUN_DATABASE_INTEGRATION_TESTS=1`에서 592개 실행, 실패 0개, Windows symlink 권한 관련 2개 건너뜀. 합성 프로젝트 렌더에서 MP4/SRT와 별도 하드 자막 MP4 생성까지 확인했다.
- 현재 API 다운로드는 기존 `final.mp4`만 제공한다. 하드 자막 파일의 API/화면 선택·다운로드는 후속 계약이 필요하다. 결과 상태는 기존처럼 프로세스 메모리 전용이다.

## 남은 검증

- 실제 촬영 영상, 장시간 렌더, 여러 클립 경계의 음성·자막 동기화, 긴 문장 줄바꿈과 가독성은 외장하드 테스트 파일을 받은 후 별도 검증한다. 합성 테스트 통과를 실제 브이로그 검증 완료로 해석하지 않는다.
- P1~P3 Ground Truth, Manifest와 평가 계약은 변경하지 않았다. 합성 파일을 공식 평가 데이터에 넣지 않았다.
