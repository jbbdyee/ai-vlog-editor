# Baseline Evaluation v0.1

## 1. 평가 목적

이 평가는 AI Vlog Editor MVP Baseline이 실제 Evaluation Dataset v0.1에서 어디까지 동작하고 어디서 실패하는지 확인하기 위한 실험이다.

평가 대상 파이프라인은 다음과 같다.

```text
MOV
→ Media Probe
→ WAV Audio Extraction
→ faster-whisper STT (small / Korean / word timestamp)
→ Rule-based Memo Detection
→ Fixed-window Scene Candidate Generation (5 / 10 / 15 / 30초)
→ Candidate Evaluation
```

평가 지표는 다음과 같다.

- IoU: Candidate와 Ground Truth의 교집합 길이 / 합집합 길이
- Coverage: Ground Truth 길이 중 Candidate가 포함한 비율
- Start Boundary Error: `abs(candidate.start - ground_truth.start)`
- End Boundary Error: `abs(candidate.end - ground_truth.end)`
- Total Boundary Error: Start Boundary Error + End Boundary Error

이 결과는 Baseline의 성능을 좋게 보이기 위한 것이 아니다. STT, Memo Detection, Fixed Window 단계에서 발생하는 실패를 실제 수치와 함께 기록하고 후속 개선의 근거로 사용한다.

## 2. Ground Truth

Ground Truth는 사람이 직접 정한 장면 구간이며 평가 과정에서 수정하지 않았다.

| Test | 영상 Duration | Ground Truth | GT 길이 |
| --- | ---: | ---: | ---: |
| Test 01 | 20.9500초 | 10.0~15.0초 | 5.0초 |
| Test 02 | 40.0500초 | 7.0~11.0초 | 4.0초 |
| Test 03 | 30.8317초 | 6.0~23.0초 | 17.0초 |
| Test 04 | 34.2000초 | 7.0~11.0초 | 4.0초 |
| Test 05 | 33.1000초 | 20.0~26.0초 | 6.0초 |

## 3. Memo Detection 결과

| Test | STT가 받아쓴 편집 메모 | 탐지 | EditMemo 시작 | 비고 |
| --- | --- | --- | ---: | --- |
| Test 01 | `에이아이아 지금 장면 꼭 살려줘.` | 성공 | 15.80초 | 현재 trigger 규칙과 일치 |
| Test 02 | `아 AIA 방금 장면 꼭 살려줘` | 실패 | N/A | `AIA`가 현재 trigger 규칙과 불일치 |
| Test 03 | `에이아이아 방금 장면 꼭 살려줘.` | 성공 | 25.94초 | 현재 trigger 규칙과 일치 |
| Test 04 | `에이아이아 방금 장면 꼭 살려줘.` | 성공 | 30.14초 | 현재 trigger 규칙과 일치 |
| Test 05 | `에이야 에야 방금 장면 꼭 살려줘` | 실패 | N/A | `에이야 에야`가 현재 trigger 규칙과 불일치 |

Test 02와 Test 05는 STT가 시간 참조인 `방금`과 편집 행동인 `살려줘`를 인식했지만 호출어를 현재 규칙 밖의 형태로 받아썼다. 따라서 Memo Detection 단계에서 중단됐으며 Scene Candidate와 평가 지표는 생성되지 않았다. 실패한 두 Test에 대해 임의의 메모 시각을 넣거나 결과를 추정하지 않았다.

## 4. Test 01~05 Candidate 평가 결과

`N/A`는 Memo Detection 실패로 Candidate가 생성되지 않아 해당 지표를 계산할 수 없음을 의미한다.

| Test | Memo Start | Window | Candidate | IoU | Coverage | Start Error | End Error | Total Boundary Error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Test 01 | 15.80초 | 5초 | 10.80~15.80초 | 0.7241 | 0.8400 | 0.80초 | 0.80초 | 1.60초 |
| Test 01 | 15.80초 | 10초 | 5.80~15.80초 | 0.5000 | 1.0000 | 4.20초 | 0.80초 | 5.00초 |
| Test 01 | 15.80초 | 15초 | 0.80~15.80초 | 0.3333 | 1.0000 | 9.20초 | 0.80초 | 10.00초 |
| Test 01 | 15.80초 | 30초 | 0.00~15.80초 | 0.3165 | 1.0000 | 10.00초 | 0.80초 | 10.80초 |
| Test 02 | N/A | 5초 | N/A | N/A | N/A | N/A | N/A | N/A |
| Test 02 | N/A | 10초 | N/A | N/A | N/A | N/A | N/A | N/A |
| Test 02 | N/A | 15초 | N/A | N/A | N/A | N/A | N/A | N/A |
| Test 02 | N/A | 30초 | N/A | N/A | N/A | N/A | N/A | N/A |
| Test 03 | 25.94초 | 5초 | 20.94~25.94초 | 0.1033 | 0.1212 | 14.94초 | 2.94초 | 17.88초 |
| Test 03 | 25.94초 | 10초 | 15.94~25.94초 | 0.3541 | 0.4153 | 9.94초 | 2.94초 | 12.88초 |
| Test 03 | 25.94초 | 15초 | 10.94~25.94초 | 0.6048 | 0.7094 | 4.94초 | 2.94초 | 7.88초 |
| Test 03 | 25.94초 | 30초 | 0.00~25.94초 | 0.6554 | 1.0000 | 6.00초 | 2.94초 | 8.94초 |
| Test 04 | 30.14초 | 5초 | 25.14~30.14초 | 0.0000 | 0.0000 | 18.14초 | 19.14초 | 37.28초 |
| Test 04 | 30.14초 | 10초 | 20.14~30.14초 | 0.0000 | 0.0000 | 13.14초 | 19.14초 | 32.28초 |
| Test 04 | 30.14초 | 15초 | 15.14~30.14초 | 0.0000 | 0.0000 | 8.14초 | 19.14초 | 27.28초 |
| Test 04 | 30.14초 | 30초 | 0.14~30.14초 | 0.1333 | 1.0000 | 6.86초 | 19.14초 | 26.00초 |
| Test 05 | N/A | 5초 | N/A | N/A | N/A | N/A | N/A | N/A |
| Test 05 | N/A | 10초 | N/A | N/A | N/A | N/A | N/A | N/A |
| Test 05 | N/A | 15초 | N/A | N/A | N/A | N/A | N/A | N/A |
| Test 05 | N/A | 30초 | N/A | N/A | N/A | N/A | N/A | N/A |

## 5. Test별 관찰

### Test 01 — 짧은 반응 직후 메모

STT와 Memo Detection이 성공했다. 5초 Candidate의 IoU는 0.7241, Coverage는 0.8400, Total Boundary Error는 1.60초였다. Window가 길어질수록 Ground Truth 전체를 포함했지만 불필요한 앞 구간이 증가해 IoU가 낮아지고 Boundary Error가 커졌다.

### Test 02 — 중요한 장면 이후 늦은 메모

STT 결과의 호출어가 `AIA`로 기록됐다. `방금`과 `살려줘`는 인식됐지만 현재 Memo Detector의 trigger 표현군과 맞지 않아 탐지에 실패했다. 이 때문에 5초 Candidate가 Ground Truth를 놓치는지에 대한 Fixed Window 가설까지 평가하지 못했다.

### Test 03 — 긴 Ground Truth

Ground Truth 길이는 17초다. 짧은 Window는 장면 앞부분을 크게 놓쳤다.

- 5초 Coverage: 0.1212
- 10초 Coverage: 0.4153
- 15초 Coverage: 0.7094
- 30초 Coverage: 1.0000

30초 Candidate는 Ground Truth 전체를 포함했지만 영상 시작부터 6초까지의 불필요한 구간도 포함해 IoU는 0.6554였다. IoU는 30초가 15초보다 높았지만 Total Boundary Error는 15초가 7.88초, 30초가 8.94초였다. 하나의 지표만으로 구간 품질 전체를 설명하기 어렵다.

### Test 04 — 장면 이후 불필요한 구간과 메모 지연

EditMemo 시작은 30.14초이고 Ground Truth는 7.0~11.0초다. 5초, 10초, 15초 Candidate는 Ground Truth와 전혀 겹치지 않아 모두 IoU 0.0000, Coverage 0.0000이었다.

30초 Candidate만 Ground Truth 전체를 포함해 Coverage 1.0000을 기록했지만 Candidate가 0.14~30.14초로 매우 길어 IoU는 0.1333, Total Boundary Error는 26.00초였다. 긴 Window가 Coverage를 회복하더라도 많은 불필요 구간을 포함할 수 있음을 보여준다.

### Test 05 — 여러 이벤트가 있는 경우

STT 결과의 호출어가 `에이야 에야`로 분리·변형됐다. `방금`과 `살려줘`는 인식됐지만 현재 trigger 규칙과 맞지 않아 Memo Detection에 실패했다. Candidate가 생성되지 않아 긴 Window가 이전 이벤트를 포함하는지에 대한 가설은 이번 실행에서 평가하지 못했다.

## 6. 실패 유형

### STT / Memo Detection 실패

- Test 02: 호출어가 `AIA`로 인식되어 Memo Detection 실패
- Test 05: 호출어가 `에이야 에야`로 인식되어 Memo Detection 실패

두 사례 모두 reference와 action은 인식됐다. 전체 발화를 놓친 것이 아니라 호출어의 STT 변형이 현재 규칙에 포함되지 않아 후속 단계가 차단됐다.

### Fixed Window 실패

- Test 03: 긴 Ground Truth에서 5초와 10초 Window의 Coverage가 각각 0.1212와 0.4153에 그쳤다.
- Test 04: 메모 지연이 커서 5초, 10초, 15초 Candidate의 IoU와 Coverage가 모두 0이었다.
- Test 04: 30초 Window는 Coverage 1.0000을 달성했지만 IoU는 0.1333으로 낮고 Total Boundary Error는 26.00초였다.

## 7. 결론

고정 Window 하나가 모든 영상에 일관되게 적합하지 않았다.

- Test 01에서는 5초 Candidate가 상대적으로 Ground Truth에 가까웠다.
- Test 03에서는 긴 장면 때문에 5초와 10초 Candidate의 Coverage가 부족했고 30초가 되어야 전체 Ground Truth를 포함했다.
- Test 04에서는 30초가 되어야 Ground Truth를 포함했지만 불필요 구간이 매우 많아 IoU가 낮았다.
- Test 02와 Test 05는 Memo Detection 실패로 Window 비교 자체가 불가능했다.

따라서 하나의 고정 시간값만으로 장면 길이와 메모 지연 차이를 동시에 처리할 수 있다는 근거는 얻지 못했다. 동시에 현재 Memo Detection은 실제 STT 호출어 변형에 의해 전체 후속 파이프라인이 차단될 수 있다.

향후 기술적 개선은 이 평가 결과와 추가 Failure Analysis를 근거로 결정한다. STT 호출어 변형 처리, 침묵 구간, transcript 문맥, 장면 전환 등은 검토 후보일 뿐이며 이 문서에서는 특정 개선 방법을 선택하거나 구현하지 않는다.
