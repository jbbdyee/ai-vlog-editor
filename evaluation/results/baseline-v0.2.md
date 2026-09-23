# Baseline Evaluation v0.2

## 1. 평가 목적

이 평가는 trigger normalization과 제한적 similarity matching이 적용된 현재 AI Vlog Editor MVP Baseline을 Evaluation Dataset `eval_01`~`eval_05`에 다시 실행해 전체 파이프라인의 실제 결과를 측정한다.

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

Clip Renderer는 이번 평가에서 실행하지 않았다. Ground Truth, STT 모델, trigger threshold, Memo Detector의 reference/action 규칙, Candidate Generator와 Evaluator는 변경하지 않았다. 결과를 좋게 보이도록 후보를 선택하거나 지표를 합산하지 않았으며, 네 Window를 모두 그대로 기록했다.

평가 지표는 다음과 같다.

- IoU: Candidate와 Ground Truth의 교집합 길이 / 합집합 길이
- Coverage: Ground Truth 길이 중 Candidate가 포함한 비율
- Start Boundary Error: `abs(candidate.start - ground_truth.start)`
- End Boundary Error: `abs(candidate.end - ground_truth.end)`
- Total Boundary Error: Start Boundary Error + End Boundary Error

## 2. v0.1 → v0.2 변경점

v0.1의 Memo Detector는 등록된 trigger variant의 exact match에 의존했다. 그 결과 Test 02의 `AIA`와 Test 05의 `에이야 에야`를 인식하지 못해 두 Test가 Candidate 단계에 도달하지 못했다.

v0.2 실행에 사용한 현재 Memo Detector는 reference 바로 앞의 제한된 토큰만 대상으로 영문 `A/I` 음가 정규화와 문자열 similarity를 적용한다. reference와 action 규칙 및 표현 순서 조건은 v0.1과 동일하다.

| 항목 | baseline-v0.1 | baseline-v0.2 |
| --- | ---: | ---: |
| Memo Detection 성공 | 3/5 | 5/5 |
| Memo Detection 성공률 | 60% | 100% |
| Candidate 평가 완료 | 3/5 | 5/5 |
| 평가된 Candidate 수 | 12개 | 20개 |

이 변화는 이 5개 Evaluation Dataset에서 관측된 결과일 뿐, 일반적인 Memo Detection 성능이나 false positive 성능을 입증하지 않는다. 특히 Test 05는 similarity `0.600`으로 현재 threshold 경계에서 일치했다.

## 3. Ground Truth와 Memo Detection 결과

Ground Truth는 사람이 직접 정한 구간이며 v0.1에서 변경하지 않았다. 메모 지연은 `EditMemo start - GT end`로 계산했다.

| Test | 영상 Duration | Ground Truth | GT 길이 | STT가 받아쓴 편집 메모 | Match Type | Similarity | Memo Start | 메모 지연 | 탐지 |
| --- | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | --- |
| Test 01 | 20.9500초 | 10.0~15.0초 | 5.0초 | `에이아이아 지금 장면 꼭 살려줘.` | similarity | 0.800 | 15.80초 | 0.80초 | 성공 |
| Test 02 | 40.0500초 | 7.0~11.0초 | 4.0초 | `아 AIA 방금 장면 꼭 살려줘` | similarity | 0.727 | 32.84초 | 21.84초 | 성공 |
| Test 03 | 30.8317초 | 6.0~23.0초 | 17.0초 | `에이아이아 방금 장면 꼭 살려줘.` | similarity | 0.800 | 25.94초 | 2.94초 | 성공 |
| Test 04 | 34.2000초 | 7.0~11.0초 | 4.0초 | `에이아이아 방금 장면 꼭 살려줘.` | similarity | 0.800 | 30.14초 | 19.14초 | 성공 |
| Test 05 | 33.1000초 | 20.0~26.0초 | 6.0초 | `에이야 에야 방금 장면 꼭 살려줘` | similarity | 0.600 | 26.84초 | 0.84초 | 성공 |

모든 Memo Start는 trigger 첫 word의 timestamp를 사용했다. Test 02와 Test 05도 trigger 개선 이후 탐지되어 Candidate 단계까지 진행됐다.

## 4. Test별 상세 결과

### Test 01 — 짧은 장면 직후 메모

- 영상 Duration: 20.9500초
- STT 편집 메모: `에이아이아 지금 장면 꼭 살려줘.`
- Trigger: `에이아이아`, similarity `0.800`
- EditMemo Start: 15.80초
- Ground Truth: 10.0~15.0초

| Window | Candidate | IoU | Coverage | Start Error | End Error | Total Boundary Error |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5초 | 10.80~15.80초 | 0.7241 | 0.8400 | 0.80초 | 0.80초 | 1.60초 |
| 10초 | 5.80~15.80초 | 0.5000 | 1.0000 | 4.20초 | 0.80초 | 5.00초 |
| 15초 | 0.80~15.80초 | 0.3333 | 1.0000 | 9.20초 | 0.80초 | 10.00초 |
| 30초 | 0.00~15.80초 | 0.3165 | 1.0000 | 10.00초 | 0.80초 | 10.80초 |

메모 지연이 0.80초로 짧고 GT 길이가 5초여서 5초 Window가 가장 가까웠다. 10초 이상에서는 Coverage가 1.0000이지만 불필요한 앞 구간이 늘면서 IoU와 경계 오차가 악화됐다.

### Test 02 — 중요한 장면 이후 매우 늦은 메모

- 영상 Duration: 40.0500초
- STT 편집 메모: `아 AIA 방금 장면 꼭 살려줘`
- Trigger: `AIA`, similarity `0.727`
- EditMemo Start: 32.84초
- Ground Truth: 7.0~11.0초

| Window | Candidate | IoU | Coverage | Start Error | End Error | Total Boundary Error |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5초 | 27.84~32.84초 | 0.0000 | 0.0000 | 20.84초 | 21.84초 | 42.68초 |
| 10초 | 22.84~32.84초 | 0.0000 | 0.0000 | 15.84초 | 21.84초 | 37.68초 |
| 15초 | 17.84~32.84초 | 0.0000 | 0.0000 | 10.84초 | 21.84초 | 32.68초 |
| 30초 | 2.84~32.84초 | 0.1333 | 1.0000 | 4.16초 | 21.84초 | 26.00초 |

v0.1에서는 trigger mismatch로 평가하지 못했으나 v0.2에서는 Fixed Window 실패가 드러났다. 메모가 GT 종료보다 21.84초 늦어 5/10/15초 Window는 GT와 전혀 겹치지 않는다. 30초 Window는 GT 전체를 포함하지만 30초 Candidate 안에서 GT는 4초뿐이므로 IoU가 0.1333에 그쳤다.

### Test 03 — 긴 Ground Truth

- 영상 Duration: 30.8317초
- STT 편집 메모: `에이아이아 방금 장면 꼭 살려줘.`
- Trigger: `에이아이아`, similarity `0.800`
- EditMemo Start: 25.94초
- Ground Truth: 6.0~23.0초

| Window | Candidate | IoU | Coverage | Start Error | End Error | Total Boundary Error |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5초 | 20.94~25.94초 | 0.1033 | 0.1212 | 14.94초 | 2.94초 | 17.88초 |
| 10초 | 15.94~25.94초 | 0.3541 | 0.4153 | 9.94초 | 2.94초 | 12.88초 |
| 15초 | 10.94~25.94초 | 0.6048 | 0.7094 | 4.94초 | 2.94초 | 7.88초 |
| 30초 | 0.00~25.94초 | 0.6554 | 1.0000 | 6.00초 | 2.94초 | 8.94초 |

GT 길이가 17초라 5초와 10초 Window는 장면 앞부분을 크게 놓쳤다. 30초 Window는 Coverage와 IoU가 가장 높지만 Total Boundary Error는 15초 Window의 7.88초보다 큰 8.94초다. 구간 품질이 한 지표로 일관되게 정리되지 않는다.

### Test 04 — 장면 이후 긴 불필요 구간과 메모 지연

- 영상 Duration: 34.2000초
- STT 편집 메모: `에이아이아 방금 장면 꼭 살려줘.`
- Trigger: `에이아이아`, similarity `0.800`
- EditMemo Start: 30.14초
- Ground Truth: 7.0~11.0초

| Window | Candidate | IoU | Coverage | Start Error | End Error | Total Boundary Error |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5초 | 25.14~30.14초 | 0.0000 | 0.0000 | 18.14초 | 19.14초 | 37.28초 |
| 10초 | 20.14~30.14초 | 0.0000 | 0.0000 | 13.14초 | 19.14초 | 32.28초 |
| 15초 | 15.14~30.14초 | 0.0000 | 0.0000 | 8.14초 | 19.14초 | 27.28초 |
| 30초 | 0.14~30.14초 | 0.1333 | 1.0000 | 6.86초 | 19.14초 | 26.00초 |

메모 지연이 19.14초라 5/10/15초 Window는 IoU와 Coverage가 모두 0이다. 30초 Window는 Coverage 1.0000을 회복하지만 26초의 Total Boundary Error와 0.1333의 낮은 IoU를 기록했다.

### Test 05 — 메모 이전에 여러 이벤트가 있는 경우

- 영상 Duration: 33.1000초
- STT 편집 메모: `에이야 에야 방금 장면 꼭 살려줘`
- Trigger: `에이야 에야`, similarity `0.600`
- EditMemo Start: 26.84초
- Ground Truth: 20.0~26.0초

| Window | Candidate | IoU | Coverage | Start Error | End Error | Total Boundary Error |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5초 | 21.84~26.84초 | 0.6082 | 0.6933 | 1.84초 | 0.84초 | 2.68초 |
| 10초 | 16.84~26.84초 | 0.6000 | 1.0000 | 3.16초 | 0.84초 | 4.00초 |
| 15초 | 11.84~26.84초 | 0.4000 | 1.0000 | 8.16초 | 0.84초 | 9.00초 |
| 30초 | 0.00~26.84초 | 0.2235 | 1.0000 | 20.00초 | 0.84초 | 20.84초 |

v0.1에서는 trigger mismatch로 평가하지 못했으나 v0.2에서는 5초 Window가 GT 앞부분을 놓쳐 Coverage가 0.6933인 것을 확인했다. 10초 Window는 GT 전체를 포함하지만 앞쪽의 불필요 구간도 포함한다. 15초와 30초로 길어질수록 Coverage는 그대로 1.0000인데 IoU는 0.4000, 0.2235로 낮아진다.

## 5. 전체 비교표

| Test | Memo Start | Window | Candidate | IoU | Coverage | Start Error | End Error | Total Boundary Error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Test 01 | 15.80초 | 5초 | 10.80~15.80초 | 0.7241 | 0.8400 | 0.80초 | 0.80초 | 1.60초 |
| Test 01 | 15.80초 | 10초 | 5.80~15.80초 | 0.5000 | 1.0000 | 4.20초 | 0.80초 | 5.00초 |
| Test 01 | 15.80초 | 15초 | 0.80~15.80초 | 0.3333 | 1.0000 | 9.20초 | 0.80초 | 10.00초 |
| Test 01 | 15.80초 | 30초 | 0.00~15.80초 | 0.3165 | 1.0000 | 10.00초 | 0.80초 | 10.80초 |
| Test 02 | 32.84초 | 5초 | 27.84~32.84초 | 0.0000 | 0.0000 | 20.84초 | 21.84초 | 42.68초 |
| Test 02 | 32.84초 | 10초 | 22.84~32.84초 | 0.0000 | 0.0000 | 15.84초 | 21.84초 | 37.68초 |
| Test 02 | 32.84초 | 15초 | 17.84~32.84초 | 0.0000 | 0.0000 | 10.84초 | 21.84초 | 32.68초 |
| Test 02 | 32.84초 | 30초 | 2.84~32.84초 | 0.1333 | 1.0000 | 4.16초 | 21.84초 | 26.00초 |
| Test 03 | 25.94초 | 5초 | 20.94~25.94초 | 0.1033 | 0.1212 | 14.94초 | 2.94초 | 17.88초 |
| Test 03 | 25.94초 | 10초 | 15.94~25.94초 | 0.3541 | 0.4153 | 9.94초 | 2.94초 | 12.88초 |
| Test 03 | 25.94초 | 15초 | 10.94~25.94초 | 0.6048 | 0.7094 | 4.94초 | 2.94초 | 7.88초 |
| Test 03 | 25.94초 | 30초 | 0.00~25.94초 | 0.6554 | 1.0000 | 6.00초 | 2.94초 | 8.94초 |
| Test 04 | 30.14초 | 5초 | 25.14~30.14초 | 0.0000 | 0.0000 | 18.14초 | 19.14초 | 37.28초 |
| Test 04 | 30.14초 | 10초 | 20.14~30.14초 | 0.0000 | 0.0000 | 13.14초 | 19.14초 | 32.28초 |
| Test 04 | 30.14초 | 15초 | 15.14~30.14초 | 0.0000 | 0.0000 | 8.14초 | 19.14초 | 27.28초 |
| Test 04 | 30.14초 | 30초 | 0.14~30.14초 | 0.1333 | 1.0000 | 6.86초 | 19.14초 | 26.00초 |
| Test 05 | 26.84초 | 5초 | 21.84~26.84초 | 0.6082 | 0.6933 | 1.84초 | 0.84초 | 2.68초 |
| Test 05 | 26.84초 | 10초 | 16.84~26.84초 | 0.6000 | 1.0000 | 3.16초 | 0.84초 | 4.00초 |
| Test 05 | 26.84초 | 15초 | 11.84~26.84초 | 0.4000 | 1.0000 | 8.16초 | 0.84초 | 9.00초 |
| Test 05 | 26.84초 | 30초 | 0.00~26.84초 | 0.2235 | 1.0000 | 20.00초 | 0.84초 | 20.84초 |

## 6. 실패 유형

### STT / Memo Detection

v0.1에서 Test 02의 `AIA`와 Test 05의 `에이야 에야`는 trigger mismatch로 Memo Detection에 실패했다. v0.2에서는 두 표현 모두 similarity matching으로 탐지돼 5개 Test 전부 Candidate 단계에 도달했다.

이번 데이터에서는 Memo Detection false negative가 관측되지 않았지만, 이것이 충분한 강건성을 뜻하지는 않는다. 데이터가 5개뿐이고 Test 05는 threshold와 같은 similarity `0.600`으로 탐지됐다. 별도의 negative dataset이 없으므로 false positive 비율은 이 평가에서 측정할 수 없다.

### Fixed Window

- 메모 지연 실패: Test 02와 Test 04는 GT 종료 후 각각 21.84초와 19.14초에 메모가 시작됐다. 5/10/15초 Window는 GT와 전혀 겹치지 않았다.
- 긴 장면 Coverage 부족: Test 03의 GT는 17초다. 5초와 10초 Window Coverage는 각각 0.1212와 0.4153이었다.
- 짧은 Window의 앞부분 손실: Test 05의 5초 Window는 GT의 앞부분을 놓쳐 Coverage가 0.6933이었다.
- 긴 Window의 불필요 구간 포함: Test 01과 Test 05에서는 Window를 늘려 Coverage 1.0000을 얻어도 IoU와 Total Boundary Error가 악화됐다.
- Coverage와 IoU 충돌: Test 02와 Test 04의 30초 Window는 Coverage 1.0000이지만 IoU는 모두 0.1333이다. GT를 포함했다는 사실만으로 후보가 정확하다고 볼 수 없다.
- 지표 간 충돌: Test 03은 30초 Window의 IoU가 0.6554로 가장 높지만 Total Boundary Error는 15초 Window의 7.88초가 더 낮다.

## 7. Fixed Window 한계

IoU 기준으로 각 Test에서 가장 높은 Window는 Test 01과 Test 05에서 5초, Test 02~04에서 30초였다. 하나의 Window가 5개 전체에서 일관되게 가장 높지 않았다.

장면 길이와 메모 지연은 서로 다른 방식으로 결과를 악화시켰다.

- 장면이 Window보다 길면 장면 앞부분을 놓쳐 Coverage가 낮아진다.
- 메모가 늦으면 Candidate 전체가 GT 뒤에 위치해 짧은 Window는 교집합이 0이 된다.
- 두 문제를 피하려고 Window를 길게 하면 GT 외의 앞·뒤 구간이 늘어 IoU가 낮아지고 경계 오차가 커진다.
- Candidate 종료 시각이 항상 Memo Start로 고정돼 있어 GT 종료 후의 메모 지연을 제거할 수 없다.

따라서 고정 Window만으로 다양한 장면 길이와 메모 지연을 동시에 처리하기 어렵다는 근거가 5개 실제 데이터에서 확인됐다. Memo Detection 개선은 Test 02와 Test 05를 평가 가능하게 만들었지만 장면 구간 추정 자체를 개선하지는 않았다.

## 8. 결론과 다음 개선 검토 근거

baseline-v0.2에서 Memo Detection 성공률은 v0.1의 60%에서 이 데이터셋 기준 100%로 증가했다. 그러나 전체 후보 품질이 함께 해결된 것은 아니다.

- Test 01과 Test 05에서는 짧은 메모 지연으로 5초 Candidate가 비교적 높은 IoU를 기록했지만 Coverage는 각각 0.8400과 0.6933이었다.
- Test 03은 긴 장면 때문에 짧은 Window가 장면 앞부분을 놓쳤다.
- Test 02와 Test 04는 긴 메모 지연 때문에 30초를 제외한 모든 Window가 GT를 완전히 놓쳤다.
- Test 02와 Test 04의 30초 Candidate도 Coverage만 1.0000일 뿐 IoU 0.1333과 Total Boundary Error 26.00초로 정확한 구간이라고 보기 어렵다.

고정 Window 하나가 모든 영상에 적합하지 않았고, Window 집합 안에서 후보를 자동 선택하는 기준도 현재 Baseline에는 없다. 장면 길이 변화와 메모 지연을 직접 다룰 다음 개선 기술을 검토할 근거는 충분히 생겼다.

침묵 구간, transcript 문맥, 시각적 장면 전환 등은 후속 Failure Analysis에서 비교할 수 있는 후보지만, 이 평가에서는 특정 기술을 선택하거나 구현하지 않았다. 다음 개선은 이 수치와 추가 평가 데이터, 특히 Memo Detector의 false positive를 측정할 negative 사례를 근거로 결정해야 한다.
