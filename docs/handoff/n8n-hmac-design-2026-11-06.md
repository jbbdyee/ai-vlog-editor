# n8n 렌더 이벤트 HMAC 인증 전환 설계·격리 검증 (2026-11-06)

상태: **설계와 격리 검증 완료, 구현·적용 안 함.**
- 제품 코드, `deploy/n8n`, 실행 중인 `cutory-n8n`(토큰·자격증명·실행 이력·볼륨), 실제 `.env`, 8000·DB·Ollama·렌더 결과는 변경하지 않았다.
- 시제품과 일회용 키는 Git 밖 임시 폴더에만 두었다.
- 선행 기록: [보안 정리](n8n-security-cleanup-2026-11-06.md), [1단계 검증](n8n-live-stage1-2026-11-06.md).

## 1. 현재 구조 (확인)

- **Cutory 전송기 (`render_events.py` `deliver`)**
  - 정렬된 compact JSON 바이트(`event.body()`)를 `content=`로 그대로 보낸다.
  - 헤더: `Authorization: Bearer <토큰>`, `X-Cutory-Event-Id`, `X-Cutory-Delivery-Id`, `X-Cutory-Attempt`
  - 재시도: 연결 오류·408·429·5xx만. 그 밖의 4xx는 `rejected`로 끝난다.
- **n8n 2.46.6 Webhook 노드 (`Webhook.node.js`)**
  - Header Auth 검증은 실행이 만들어지기 **전에** 노드 안(`validateAuth`)에서 한다. 실패하면 403을 바로 응답하고 실행 이력을 남기지 않는다.
  - 통과하면 출력 `json.headers`에 요청 헤더 전체가 들어간다. 이 출력이 실행 데이터로 DB에 기록되므로 Bearer 토큰이 평문으로 남는다.
- **원본 바이트**
  - Webhook v2 옵션 `rawBody: true`이면 `req.rawBody`를 base64로 `binary.data`에 넣는다(271–285행).
  - n8n이 파싱한 객체 `json.body`도 함께 들어간다.
- **Code 노드 샌드박스 (task runner internal 모드)**
  - `process`·`globalThis.crypto.subtle` 없음, `Buffer`·`TextEncoder` 있음
  - `$env`는 `access to env vars denied`
  - `require`는 `NODE_FUNCTION_ALLOW_BUILTIN` 목록만 허용한다.
  - `this.helpers.getBinaryDataBuffer(0, 'data')` 사용 가능
- **Webhook 인증 옵션:** `basicAuth`, `headerAuth`, `jwtAuth`, `none`(+ n8n OAuth2). HMAC 본문 서명은 내장 기능이 없다.

## 2. 격리 검증 결과

검증 환경:
- 같은 고정 이미지로 일회용 probe 컨테이너를 띄웠다(전용 네트워크, `127.0.0.1:5680`, 볼륨 없음, `--rm`).
- 무작위 키 2개(k1, k2)를 Git 밖 파일로 만들어 읽기 전용으로 마운트했다.
- 확인 후 컨테이너와 네트워크를 삭제했다.

| 확인 | 결과 |
| --- | --- |
| `NODE_FUNCTION_ALLOW_BUILTIN=fs,path`(현재)에서 `require('crypto')` | **불가**: `Module 'crypto' is disallowed`. WebCrypto(`crypto.subtle`)도 없음 |
| `crypto,fs,path`로 허용 | `createHmac('sha256')`, `timingSafeEqual` 정상 |
| 원본 바이트 | `rawBody: true` → 인라인 base64와 `getBinaryDataBuffer` 결과가 같고, Cutory 본문 428바이트와 일치 |
| JSON 재직렬화 | **원본과 다름.** Python `12.0` → JS `JSON.stringify` `12`(428→426바이트). 재직렬화 바이트로는 서명이 맞지 않아 401 |
| 비밀키 읽기 | 읽기 전용 마운트 파일을 `fs.readFileSync`로 읽을 수 있음. `$env`는 차단 |
| 한글·실수 본문 | 원본 바이트로 HMAC 일치 |
| 실행 이력 | probe는 실행을 모두 저장(기본값)했다(`crypto` 허용 probe, 30건). 30건 모두 서명 헤더는 있으나 **키 바이트(hex·raw)는 DB·WAL·로그 등 파일 10개 어디에도 0회** |

시제품 검사(검증 단계 + 기존 `record-render-event.js` 기록 로직):
- **Node 하네스 23/23 통과.** n8n 샌드박스를 흉내 냈고 `fs` 쓰기 함수를 감시했다.
  - 거부 17가지: 헤더 없음, 틀린 서명, 짧은 서명, 대문자 hex, 모르는 kid, `__proto__`·`constructor` kid, ±301초, 숫자 아닌 시각, 서명 후 본문·시각 변경, 재직렬화 본문, 키 링에서 제거된 kid, 키 링 읽기 실패 500, 서명된 비JSON 400, 서명됐지만 스키마 위반 400
  - 위 17가지 모두 **쓰기 호출 0회, 기록 폴더 미생성.**
  - 허용 경로: `recorded`, k2 서명 `duplicate`, 같은 요청 재전송 `duplicate`, 같은 ID·다른 본문 409, 기록 1개
- **probe n8n 종단 15/15 통과.**
  - 401: 헤더 없음, 틀린 서명, 모르는 kid, ±310초, 서명 후 본문 교체, 재직렬화 본문 → 해당 이벤트 기록 없음
  - 200: 정상 `recorded`, 같은 요청 재전송 `duplicate`, k2 `duplicate`
  - 409: 같은 ID·다른 본문 → 기록 1개, 임시 파일 0
  - ±290초는 200
- **경계 관찰:**
  - 첫 실행에서 +301초 요청이 통과했다.
  - 원인: 송신 측 정수 초에 301을 더한 뒤 수신 측 시계가 다음 초로 넘어가 차이가 300이 됐고, 허용 조건이 `≤300`이었다.
  - 호스트와 컨테이너 시계 차이는 약 5ms로 무관했다.
  - 실제 허용 오차는 **300초 ± 1초 양자화**다. 테스트는 경계에서 떨어진 값(±290 / ±310)을 쓴다.

## 3. 권장 구조

### 서명

```
signed = b"v1:" + <X-Cutory-Timestamp ASCII> + b":" + <정확한 요청 본문 바이트>
X-Cutory-Signature = lower-hex( HMAC-SHA256( key_bytes(kid), signed ) )
헤더: X-Cutory-Key-Id, X-Cutory-Timestamp(10자리 유닉스 초), X-Cutory-Signature(64 hex)
     + 기존 X-Cutory-Event-Id·X-Cutory-Delivery-Id·X-Cutory-Attempt(서명 대상 아님, 추적용)
Authorization 헤더는 보내지 않는다.
```

- **송신 측:**
  - 이미 만든 `body` 바이트를 그대로 서명하고 그대로 보낸다. 서명 직전에 다시 직렬화하지 않는다.
  - **시도마다 새 타임스탬프로 다시 서명한다.** 재시도 간격 1·4·15초, 재전송 CLI는 몇 시간 뒤일 수 있다.
- **수신 측:**
  - `rawBody: true`로 받은 바이트로 검증한다.
  - 검증이 통과한 뒤 **그 바이트를 `JSON.parse`한 값만** 스키마 검증·기록에 쓴다. n8n이 파싱한 `json.body`는 쓰지 않는다.
- **키:** 32바이트 무작위 hex(64자). 접두어 `v1`은 형식을 바꿀 때 버전을 구분하는 용도다.

### 검증 순서 (기록 차단 보장)

모든 거부는 기록 단계 앞에서 `return`한다. 기록 단계(`mkdirSync`·`writeFileSync`·`linkSync`)는 서명 검증과 스키마 검증을 모두 통과한 값으로만 실행된다. Node 하네스가 이를 쓰기 호출 0회로 확인했다.

1. 헤더 형식: kid `^[a-z0-9][a-z0-9_-]{0,31}$`, ts 10자리, 서명 64 소문자 hex → 실패하면 401
2. `|지금 − ts| ≤ 300초` → 실패하면 401 `TIMESTAMP_SKEW`
3. 키 링 파일 읽기 → 실패하면 500 `KEYRING_UNAVAILABLE`(Cutory 재시도). kid는 `hasOwnProperty`로만 조회해 프로토타입 키를 막는다.
4. 원본 바이트: 없거나 16KB를 넘으면 401
5. `timingSafeEqual`(길이는 1단계에서 64 hex로 고정) → 실패하면 401 `SIGNATURE`
6. 검증된 바이트를 `JSON.parse` → 실패하면 400 → 기존 스키마 검증(400) → 기존 기록(200/409/500)

응답 코드와 Cutory 동작:
- 401: 재시도하지 않는다(`rejected`). 시계 차이 때문인지 바로 보이도록 오류 코드를 전송 기록에 남기는 것을 권장한다. 지금은 `receiver_result`만 허용 목록에 있으므로 `receiver_error` 허용 목록을 추가한다.
- 500: 키 링 문제는 재시도한다.

### 비밀키 보관

| 위치 | 방식 |
| --- | --- |
| n8n | 호스트의 Git 밖 경로(예: 사용자 프로필 아래 전용 폴더, Windows ACL로 본인만)에 `keys.json` `{"k2026a": "<hex>"}`를 두고 compose에서 `/run/cutory-hmac`로 **읽기 전용** 마운트. Code 노드가 요청마다 읽는다. 워크플로우 JSON·자격증명·실행 데이터에는 키가 들어가지 않는다 |
| Cutory | 실제 `.env`의 `CUTORY_N8N_WEBHOOK_HMAC_KEY_ID`, `CUTORY_N8N_WEBHOOK_HMAC_SECRET`(64자 이상 hex). 기존 `..._TOKEN`은 제거 |

### 타임스탬프·nonce·재전송

- **허용 오차 ±300초:**
  - 재시도 전체(약 20초)와 Windows·Docker Desktop VM 시계 차이(측정 약 5ms)를 충분히 덮는다.
  - 시도마다 다시 서명하므로 송신 지연은 시도 하나 길이(타임아웃 3초)뿐이다.
  - 60초까지 줄일 수 있지만, VM이 절전에서 깨어날 때 시계가 어긋나는 경우에 대비해 300초를 권장한다.
- **nonce 저장소는 MVP에서 두지 않기를 권장한다.**
  - 서명이 본문 전체를 덮기 때문에, 가로챈 요청을 다시 보내도 같은 이벤트·같은 내용이라 결과는 `duplicate`(200)뿐이다. 새 기록이나 충돌을 만들 수 없다.
  - 기존 이벤트 ID와 내용 비교 중복 처리를 그대로 유지하는 것이 핵심이다.
  - 시간 창은 오래된 요청의 무기한 재사용을 막는다.
- **nonce가 필요해지는 조건:** 서명된 요청이 상태를 바꾸는 동작(삭제·외부 알림 발송 등)을 일으키게 될 때.
  - 그때는 `X-Cutory-Delivery-Id:attempt`를 서명 대상에 넣는다.
  - 수신 측은 `nonce/<id>` 파일을 `link`로 원자적으로 만들고(이미 있으면 401), 시간 창이 지난 항목을 정리한다.
- **기존 이벤트 ID `render-<hex>-<status>`는 그대로 유지한다.** 중복 기록 판단용이며 서명과는 독립적이다.

### 키 교체

- n8n 키 링은 여러 kid를 동시에 허용한다. Cutory는 항상 하나의 kid로 서명한다. 프로브에서 k1·k2 동시 허용을 확인했다.
- **절차:**
  1. 새 키를 n8n 키 링에 추가한다(요청마다 파일을 읽으므로 n8n 재시작 불필요).
  2. Cutory `.env`의 kid·키를 바꾸고 8000을 재시작한다.
  3. 전송 기록에서 새 kid로 `delivered`를 확인한다.
  4. 하루 정도 지난 뒤 옛 키를 키 링에서 제거한다.
  - 재전송 CLI도 현재 키로 새로 서명하므로, 과거 이벤트 때문에 옛 키를 남겨 둘 필요는 없다.
- **주기:** 유출이 의심되면 즉시 교체한다. 정기 교체는 90일을 권장한다(단일 사용자 로컬 환경 기준).

### 남는 노출

- 실행 데이터에는 서명·kid·타임스탬프·원본 본문이 남는다(기존 설정으로 약 1분 안에 삭제, 바이트 잔존은 [보안 정리](n8n-security-cleanup-2026-11-06.md)와 같음).
- **이것으로 비밀키를 알아낼 수는 없다.** 가능한 것은 시간 창 안에서 같은 요청을 다시 보내는 것뿐이고, 결과는 `duplicate`다.

### Webhook 인증을 `none`으로 바꾸는 영향

- 서명이 없는 요청도 실행을 만든다. 이 실행은 401로 끝나고 1분 안에 삭제되며 비밀값은 없다.
- `127.0.0.1` 공개는 유지한다.
- Webhook 노드의 `ipWhitelist` 옵션은 Docker Desktop 포트 프록시를 거칠 때 들어오는 원본 IP가 무엇인지 확인하지 못해 미검증이다. 필요하면 별도로 확인한다.

## 4. 대안 비교

| 방안 | 판단 |
| --- | --- |
| **A. Code 노드 `crypto` + 읽기 전용 키 링 파일 (권장)** | 실제 동작 확인. 비밀값이 요청·워크플로우·실행 데이터에 없음. 필요한 변경: `NODE_FUNCTION_ALLOW_BUILTIN`에 `crypto` 추가, 마운트 1개 |
| B. n8n Crypto 노드(HMAC 동작) | 키가 노드 파라미터에 평문으로 들어가 워크플로우 DB·export·Git에 남을 위험. `$env` 차단이라 우회도 안 됨. 비권장 |
| C. Webhook 내장 JWT Auth | 키는 n8n 자격증명에 암호화 저장되고 n8n이 실행 전에 검증. 다만 JWT 자체는 헤더에 있어 실행 이력에 남고(만료 전 재사용 가능), 본문 결합에는 본문 해시 claim과 해시 계산이 필요(Code 노드 `crypto` 또는 미검증 표현식). 구성 요소가 늘어 이점이 적다. 미검증 |
| D. `crypto` 없이 순수 JS로 SHA-256/HMAC 구현 | 직접 만든 암호 구현이라 비권장. 요청대로 구현하지 않음 |
| E. Bearer 유지 + 1분 삭제(현재) | 동작 중. 실행 중·삭제 전·바이트 잔존 구간에 실제 비밀값이 노출됨 |

## 5. 예상 변경 파일 (구현 승인 시)

| 파일 | 변경 |
| --- | --- |
| `backend/app/services/render_events.py` | 설정을 Bearer 토큰에서 kid·HMAC 키로 변경(형식·길이 검증, repr 숨김), `sign_request(body, ts, kid, key)`, 시도마다 서명, `Authorization` 제거, `receiver_error` 허용 목록 |
| `backend/app/main.py` | 설정 오류 코드 이름만 갱신(구조 변경 없음 예상) |
| `backend/app/render_event_replay.py` | 변경 없음 예상(전송기 사용) |
| `backend/tests/test_render_events.py` | 설정·헤더·서명 테스트, 가짜 수신기를 HMAC 검증으로 변경, 시도별 타임스탬프 |
| `deploy/n8n/record-render-event.js` | 위 검증 단계를 기록 로직 앞에 삽입(시제품의 `hmac-gate.js`, 부록) |
| `deploy/n8n/build_workflow.py` + JSON | Webhook `authentication: none`, `options.rawBody: true` |
| `deploy/n8n/docker-compose.yml` | `NODE_FUNCTION_ALLOW_BUILTIN=crypto,fs,path`, 키 링 읽기 전용 마운트(호스트 경로는 Git 밖 변수) |
| `deploy/n8n/check-record-render-event.mjs` | HMAC 경우 + `fs` 쓰기 감시(시제품 하네스 이식) |
| `deploy/n8n/check-live-n8n.py` | 서명 송신 |
| 신규 `deploy/n8n/hmac-test-vectors.json` | 고정 **테스트 전용** 키·ts·본문·서명. Python·Node 양쪽 테스트가 같은 값을 쓰는지 확인 |
| `.env.example`, `deploy/n8n/README.md`, 문서 | 변수 이름·절차·상태 |

## 6. 테스트 계획

1. **Python 단위:**
   - 테스트 벡터 서명 일치
   - 재시도마다 ts·서명이 바뀌고 본문은 바이트 그대로인지
   - `Authorization` 헤더가 없는지
   - 로그·repr에 키가 없는지
   - 설정 거부(짧은 키, hex 아님, kid 형식)
2. **Node(`check-record-render-event.mjs`):**
   - 같은 테스트 벡터 검증
   - 시제품 23항목(거부 시 쓰기 0회 포함)
   - 기존 17항목, 8개 프로세스 동시 중복
3. **가짜 수신기(127.0.0.1 임의 포트):** Python으로 HMAC을 검증해 401/200 왕복. 렌더 상태가 바뀌지 않는지 확인
4. **격리 n8n:**
   - 일회용 probe 또는 승인 후 `cutory-n8n`에서 `check-live-n8n.py` HMAC판
   - 실행 이력·로그에서 키 바이트 0회, 서명 헤더만 있는지 스캔
5. **8000 연동(별도 승인):** 기존 완료 렌더 4건 `--send` 또는 실제 렌더 1회

## 부록: 검증 단계 시제품 (probe·하네스에서 실행한 그대로)

`record-render-event.js`의 `const body = items[0].json.body;` 한 줄을 아래 블록으로 바꾼 형태로 시험했다. 제품 파일에는 적용하지 않았다.

```js
const crypto = require('crypto');
const KEYRING_FILE = '/run/cutory-hmac/keys.json';
const MAX_SKEW_SECONDS = 300;
const MAX_BODY_BYTES = 16384;
const hdr = items[0].json.headers || {};
const deny = (code) => answer(401, { result: 'unauthorized', error: code });
const kid = hdr['x-cutory-key-id'];
const tsText = hdr['x-cutory-timestamp'];
const sigHex = hdr['x-cutory-signature'];
if (typeof kid !== 'string' || !/^[a-z0-9][a-z0-9_-]{0,31}$/.test(kid)) return deny('KEY_ID');
if (typeof tsText !== 'string' || !/^[0-9]{10}$/.test(tsText)) return deny('TIMESTAMP');
if (Math.abs(Math.floor(Date.now() / 1000) - Number(tsText)) > MAX_SKEW_SECONDS) return deny('TIMESTAMP_SKEW');
if (typeof sigHex !== 'string' || !/^[0-9a-f]{64}$/.test(sigHex)) return deny('SIGNATURE_FORMAT');
let keyring;
try { keyring = JSON.parse(fs.readFileSync(KEYRING_FILE, 'utf8')); } catch (e) { return answer(500, { result: 'error', error: 'KEYRING_UNAVAILABLE' }); }
const secretHex = Object.prototype.hasOwnProperty.call(keyring, kid) ? keyring[kid] : null;
if (typeof secretHex !== 'string' || !/^[0-9a-f]{64,}$/.test(secretHex)) return deny('KEY_ID');
let raw;
try { raw = await this.helpers.getBinaryDataBuffer(0, 'data'); } catch (e) { return deny('RAW_BODY'); }
if (!Buffer.isBuffer(raw) || raw.length === 0) return deny('RAW_BODY');
if (raw.length > MAX_BODY_BYTES) return deny('BODY_TOO_LARGE');
const expected = crypto.createHmac('sha256', Buffer.from(secretHex, 'hex')).update(`v1:${tsText}:`, 'utf8').update(raw).digest();
if (!crypto.timingSafeEqual(Buffer.from(sigHex, 'hex'), expected)) return deny('SIGNATURE');
let body;
try { body = JSON.parse(raw.toString('utf8')); } catch (e) { return answer(400, { result: 'invalid', error: 'JSON' }); }
```
