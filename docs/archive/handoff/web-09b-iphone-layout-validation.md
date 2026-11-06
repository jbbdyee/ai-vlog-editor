# WEB-09B — iPhone 13 mini 화면 잘림 조사·수정

상태: **React UI 수정·모바일 Chrome 에뮬레이션 검증 완료, 수정 후 실기기 검증 미실행**. 작업 시작 `main`, HEAD `1a2d7d71c4c2bbdc8d01a917227cd176d7fc7843`. 기존 WEB-01~09/EVAL/WEB-08B 미커밋 작업과 보호 대상 백엔드 테스트 3개를 보존했다. Git 커밋·Push 없음.

## 원인 조사

사용자는 Tailscale로 연 실제 iPhone 13 mini에서 프로젝트 화면 왼쪽, 단계 이동, 영상 등록 카드가 가로로 밀려 잘린다고 보고했다. 실제 스크린샷 파일과 Safari 개발자 도구의 `visualViewport` 수치는 이 작업 공간에 제공되지 않았다. 따라서 **실기기에서 정확히 어떤 상태가 원인이었는지는 확정하지 않는다**.

- `web/index.html`의 viewport meta는 `width=device-width, initial-scale=1.0`으로 정상이다. 전역 CSS는 `body { min-width: 320px }`였고 루트 레이아웃은 모바일 좌우 12px 패딩을 사용했다. 프로젝트의 단계 이동 바에는 `-mx-3`과 보정 패딩이 있었다. UUID와 긴 파일명은 WEB-09에서 줄바꿈하도록 처리했으며 이 단계에서 새 고정 너비·`max-content`는 발견하지 못했다.
- 기존 WEB-09 Playwright 테스트는 데스크톱 Chrome의 `viewport` 너비만 바꿨다. 모바일 `isMobile`, 터치, DPR 3, iPhone 사용자 에이전트와 `visualViewport`를 검사하지 않았다. 또한 `documentElement.scrollWidth <= clientWidth`만으로 브라우저의 실제 표시 폭과의 차이를 모두 설명할 수 없다.
- 기존 코드의 모바일 Chrome 재현: 300 CSS px 표시 영역에서 `documentElement.clientWidth=300`, `scrollWidth=321`, `body.clientWidth=320`, 루트 너비 320, 단계 바 오른쪽 308, 등록 카드 오른쪽 308이었다. **320px 최소 너비가 더 좁은 표시 영역을 넘기는 확정된 결함**이다. 같은 코드의 표준 iPhone 13 mini 375px 에뮬레이션은 `clientWidth=scrollWidth=375`로 넘침이 없었다. 실제 사용자의 Safari/앱 내 브라우저가 300px에 가까운 표시 폭이나 확대 상태였는지는 미확인이다.
- 모바일 14px 입력 글자는 Safari 포커스 시 화면 확대에 기여할 가능성이 있어 16px로 조정했다. 이 확대 가설은 실제 Safari에서 재현·확인되지 않았다. 사용자가 수동으로 확대했거나, 앱 내 브라우저의 표시 영역·캐시가 달랐을 가능성도 남는다.

## 최소 수정

- `web/src/index.css`: `body`의 320px 최소 너비 제거. 가로 넘침을 숨기는 `overflow-x: hidden`은 추가하지 않음.
- `web/src/features/projects/project-page.tsx`: 단계 바의 음수 바깥 여백과 보정 패딩을 제거하고 상위 콘텐츠 너비 안에 배치. 기존 3열 모바일/5열 데스크톱 링크, sticky 동작과 섹션 ID는 유지.
- `web/src/components/ui/input.tsx`: 입력의 `min-w-0 max-w-full`과 모바일 16px 글자 적용. `sm` 이상은 기존 14px 유지. 파일 입력도 공통 컴포넌트를 사용한다.
- `web/e2e/web09-responsive.spec.ts`: 모바일 viewport 조건을 추가하고 `html/body/#root/main/nav/upload/input/processing`의 양쪽 bounding box와 전체 너비를 검사한다.

## 검증과 한계

| 항목 | 결과 |
| --- | --- |
| 모바일 Chrome 에뮬레이션 | iPhone 13 mini 사용자 에이전트, 모바일 viewport, 터치, DPR 3에서 300·375px 홈·프로젝트 화면의 `scrollWidth`, `clientWidth`, `visualViewport.width`와 주요 컴포넌트 좌·우 경계를 확인. 수정 후 모두 표시 폭 이내 |
| 기존 뷰포트 | 320·375·390·430px와 1440px 홈·프로젝트 화면 및 단계 이동·두 플레이어 너비 검사 통과 |
| 시각 자료 | Git 제외 `web/test-results/`의 에뮬레이션 캡처만 사용. 실제 iPhone 스크린샷 검증으로 집계하지 않음 |
| 기능 회귀 | React 단위 **33건 통과**, 모의 API Chrome **14건 통과**(기존 7건과 WEB-09/09B 레이아웃 7건), TypeScript `tsc -b` 및 Vite production build 통과. 실패·건너뜀 0건 |

수정 후 실제 iPhone 13 mini Safari와 앱 내 브라우저를 각각 새로고침해 제목·단계 바·영상 등록 카드, 입력 포커스 전후 확대, `visualViewport.width/scale`, 가로 스크롤을 확인해야 한다. 화면 확대가 유지된다면 Safari 주소창·브라우저 확대 상태를 초기화하고 캐시된 Vite 리소스 여부도 확인한다. 이 단계는 백엔드 API, PostgreSQL, Tailscale Serve, 원본·GT·Manifest·렌더 결과를 변경하지 않았다.
