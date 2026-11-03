# WEB-06 — 원본 영상 및 SceneCandidate 미리보기

상태: **로컬 구현·제한된 실제 Chrome 검증 완료**. 2026-10-26 Windows `main`, 시작 HEAD `1a2d7d71c4c2bbdc8d01a917227cd176d7fc7843`. 기존 WEB-01~05/EVAL-01/02 미커밋 작업, 백엔드 테스트 3개, 평가 자료와 원본은 보존했다. 커밋·Push 없음. [WEB-05 분석](web-05-ux-gap-analysis.md)의 원본·후보 화면 재생 P0 공백을 대상으로 하며 SceneCandidate 생성·추천 품질은 평가하지 않았다.

## 실제 영상과 호환성 판단

| 등록 원본 | FFprobe 영상/오디오 | 길이 | 원본 SHA-256 |
| --- | --- | ---: | --- |
| `evaluation/data/P1/P1_S01_take01.MOV` | HEVC Main 10 `hvc1`, 10-bit `yuv420p10le` / AAC `mp4a` | 13.498초 | `205e4143822520183d446c154fc314f607b3c948ec2e264b37195933d89a01d2` |
| `evaluation/data/P1/P1_S02_take01.MOV` | HEVC Main 10 `hvc1`, 10-bit `yuv420p10le` / AAC `mp4a` | 36.228초 | `f158d2260bd3c7b48d0d88a130d922ba0c8d20f191820ec8af0f58b1af78ce95` |

두 영상은 기존 WEB-04 격리 QA 프로젝트에 등록된 사본을 **읽기 전용**으로 사용했다. 현재 로컬 Windows Chrome은 두 MOV의 메타데이터·양수 영상 크기, `play()` 성공, seek 뒤 시간 진행과 실제 디코딩 프레임 증가를 확인했다. 새 프로젝트 업로드·분석·렌더를 실행하지 않았다. 이 환경에서는 프록시 MP4가 필요하다는 근거가 없어 FFmpeg 변환과 프록시 저장 기능을 추가하지 않았다. 다른 Windows 설정, macOS/Linux, 모바일 브라우저의 HEVC 지원은 미검증이다.

## API와 접근 경계

`GET /projects/{project_id}/sources/{source_id}/media`는 두 UUID만 받는다. DB에 프로젝트와 소스가 존재하고 해당 소스가 프로젝트에 속해야 한다. DB의 내부 `storage_reference`가 정해진 프로젝트 저장 공간에 있어야 하며, 정규식·저장 루트·정확한 실제 경로를 검사한다. 잘못된 참조, 루트 이탈·심볼릭 링크, 파일 누락·빈 파일은 404다. MOV는 `video/quicktime`, MP4는 `video/mp4`, `Content-Disposition: inline`, `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff`로 응답한다. Starlette `FileResponse`가 청크 스트리밍과 `Accept-Ranges: bytes`, 정상 범위의 206·`Content-Range`, 잘못된 범위의 416을 처리한다. 전체 파일을 앱 메모리에 올리지 않는다.

API는 요청 클라이언트가 loopback 주소일 때만 응답하며, FastAPI와 Vite는 `127.0.0.1`에 바인딩한다. **UUID와 소스 소속 검사는 인증·사용자별 소유권 검증이 아니다.** 리버스 프록시가 외부 요청을 loopback으로 전달할 수 있으므로 이 경계를 공개 서비스 보안으로 사용하지 않는다. 외부 공개 배포 금지. 원본 사용자 파일명은 응답의 다운로드 파일명에 쓰지 않는다.

## React 동작

프로젝트 화면에 등록 소스 선택기와 `<video>` 플레이어를 추가했다. 후보 카드·선택 가능 목록·선택 순서 목록의 미리보기 동작은 후보의 `source_video_id`, `start_seconds`, `end_seconds`를 같은 플레이어에 전달한다. 후보 시작으로 탐색하고 종료에서 일시정지하며, 다른 소스·후보·프로젝트로 옮기면 기존 플레이어 상태를 정리한다. 원본 전체 보기로 구간 제한을 해제한다. 오류 안내가 떠도 후보 선택과 편집 계획 저장은 계속 가능하다. 선택 순서 목록에는 원본 파일명·시각·구간 길이·현재 미리보기 표시를 추가했다. 브라우저 seek와 `timeupdate`는 근사 동작이며 프레임 정확도를 보장하지 않는다.

초기 실제 브라우저 실행 로그에서 같은 프로젝트 ID를 세 형제 컴포넌트의 React `key`로 재사용해 중복 키 경고가 나왔다. 프로젝트 전환 상태 보존을 위해 이 키를 `preview:`, `scene:`, `edit:`로 분리했고 최종 검증에 포함했다.

## 검증 결과

| 수준 | 실행·결과 |
| --- | --- |
| 백엔드 전용 | `python -m unittest backend.tests.test_source_media_api -q`: 5건 중 4 통과, 1 Windows symlink 생성 권한으로 건너뜀, 실패 0. 전체/206/416, MIME, 다른 프로젝트·없는 ID, 잘못된 참조·누락 파일, 원본 바이트 불변, 원격 클라이언트 거부를 확인 |
| 관련 백엔드 회귀 | `python -m unittest backend.tests.test_source_media_api backend.tests.test_project_render_api -q`: 13건 중 11 통과, 위 symlink와 기존 Windows 권한 사례 각 1건씩 건너뜀, 실패 0. 보호 대상 기존 테스트 파일은 수정하지 않음 |
| React 단위·Mock API | `pnpm test`: 27건 통과, 실패·스킵 0. 신규 플레이어 소스 선택·짧은 구간 종료·오류 표시·프로젝트 전환, 선택 목록의 소스명·길이·미리보기 연결과 기존 프로젝트/편집 계획 테스트 포함. jsdom의 미디어 디코딩은 Mock이며 실제 재생 증거가 아님 |
| 타입·빌드 | `pnpm build`: TypeScript 검사·Vite 빌드 통과 |
| 실제 Chrome + FastAPI + PostgreSQL | 기존 등록 프로젝트에 `WEB06_PROJECT_ID`를 지정한 `web06.spec.ts` 1건 통과. Vite 프록시를 통한 원본 Range 응답, 두 MOV 로드·재생·seek·디코딩 프레임 증가, 첫 2.44~2.62초 후보 이동과 종료 정지 확인. 서버 로그의 미디어 요청은 206이며 별도 API 호출도 206·정확한 1024바이트 `Content-Range` 확인 |

테스트만으로 P1 원본 전체 프레임·오디오 지각 품질, 모든 후보의 프레임 경계, 다른 브라우저·OS를 검증했다고 말하지 않는다. 오디오 스트림 존재는 FFprobe로 확인했으나 실제 청취 품질은 평가하지 않았다. 선택 목록 기존 순서 변경·저장은 단위 회귀 범위이며 WEB-06에서 새 편집 계획 저장을 실제 Chrome으로 재실행하지 않았다.

## 남은 위험과 후속 작업

1. 다른 브라우저의 HEVC 재생 실패가 실제 재현되면, 원본을 보존하는 별도 H.264/AAC 프록시의 안전한 생성·캐시·수명주기를 설계한다. 현재 모든 영상에 재인코딩을 적용하지 않는다.
2. 짧은 구간의 탐색·정지는 브라우저 키프레임 및 이벤트 시간에 영향을 받는다. 프레임 정확한 컷 검증은 최종 렌더 산출물 기준으로 별도 수행한다.
3. 인증·사용자 소유권이 없고 로컬 IP 검사는 리버스 프록시 환경의 보호책이 아니다. 공개 배포 전에 별도 접근 제어가 필요하다.
4. 최종 MP4 화면 재생과 렌더 상태 재시작 복구는 WEB-06 범위에서 구현하지 않았다. GT 미동결 및 SceneCandidate 정량 품질 평가 미완료 상태도 유지한다.
