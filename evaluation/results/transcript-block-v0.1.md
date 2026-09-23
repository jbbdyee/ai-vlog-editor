# Transcript Block Scene Retrieval Evaluation v0.1

## 1. 실험 목적

Fixed Window baseline-v0.2에서는 장면 길이와 메모 지연이 영상마다 달라 하나의 Window가 모든 Test에 적합하지 않았다. 이 실험은 LLM이나 의미 분석을 도입하기 전에, 메모 이전 TranscriptSegment의 발화 경계만으로 만든 최신 utterance block이 Ground Truth에 더 가까운 Scene Candidate를 만들 수 있는지 평가한다.

실행 파이프라인은 다음과 같다.

```text
STT (small / Korean / word timestamp)
→ Memo Detector
→ Transcript Block Builder
→ Latest Block Selector
→ SceneCandidate
→ 기존 CandidateEvaluator
```

Ground Truth는 retrieval 입력에 사용하지 않고 Candidate 생성 완료 후 평가에만 사용했다. Fixed Window, STT, Memo Detector, Evaluator, Ground Truth는 변경하지 않았으며 자동 fallback도 사용하지 않았다.

## 2. Block 생성 및 선택 규칙

1. 전체 TranscriptSegment의 timestamp와 순서를 검증한다.
2. `segment.end_seconds <= memo.start_seconds`인 segment만 context로 사용한다.
3. memo segment와 memo 이후 segment는 제외한다.
4. 인접 segment 사이 `gap = current.start - previous.end`를 계산한다.
5. `gap > 2.0초`이면 새 block을 시작한다.
6. 가장 최근 block 하나를 의미 분석 없이 선택한다.
7. 선택 block의 start/end를 그대로 `SceneCandidate`로 변환한다.
8. Candidate의 `window_seconds`에는 block의 실제 길이인 `end - start`를 기록한다.

### Silence Threshold

모든 Test에 동일한 **2.0초** threshold를 사용했다. 짧은 호흡이나 문장 전환은 같은 발화 흐름으로 유지하면서 2초를 초과하는 침묵은 별도 utterance로 분리하는 첫 Baseline 값이다. 이 값은 eval 결과를 실행하기 전에 고정했으며 Test별 또는 결과 확인 후 조정하지 않았다. 간격이 정확히 2.0초이면 같은 block으로 유지한다.

## 3. Test 01 결과

- 영상 Duration: 20.9500초
- Memo Start: 15.80초
- Ground Truth: 10.0~15.0초

| Block | 구간 | Segment IDs | Transcript |
| --- | ---: | --- | --- |
| block-0001 | 1.24~9.90초 | segment-0001~0003 | `안녕하세요. 저는 김사과입니다. 지금은 간단한 동영상 테스트를 해보고 있습니다. 제가 물건을 하나 떨어뜨려 볼게요.` |
| **block-0002 (선택)** | **12.70~13.18초** | segment-0004 | `아 뭐야.` |

| Candidate | IoU | Coverage | Start Error | End Error | Total Boundary Error |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 12.70~13.18초 | 0.0960 | 0.0960 | 2.70초 | 1.82초 | 4.52초 |

최신 반응 발화는 GT 안에 있지만 0.48초뿐이다. Transcript에 없는 무음·시각 구간을 후보에 포함하지 못해 Fixed Window 5초의 IoU 0.7241보다 크게 낮았다.

## 4. Test 02 결과

- 영상 Duration: 40.0500초
- Memo Start: 32.84초
- Ground Truth: 7.0~11.0초

| Block | 구간 | Segment IDs | Transcript |
| --- | ---: | --- | --- |
| block-0001 | 3.04~10.96초 | segment-0001~0002 | `2번째 테스트 영상입니다 아 뭐야 떨어졌네` |
| **block-0002 (선택)** | **14.00~23.80초** | segment-0003~0006 | `다시 주었습니다 오늘은 영상 테스트를 하고 있는데요 이제 책상도 좀 정리하고 다음 테스트도 해보겠습니다` |

| Candidate | IoU | Coverage | Start Error | End Error | Total Boundary Error |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 14.00~23.80초 | 0.0000 | 0.0000 | 7.00초 | 12.80초 | 19.80초 |

실제 중요 사건은 block-0001에 가깝지만 최신 block 규칙은 이후의 무관한 설명인 block-0002를 선택했다. Fixed Window 30초의 IoU 0.1333보다도 낮으며, 시간 경계만으로 여러 과거 사건 중 올바른 사건을 선택할 수 없음을 보여준다.

## 5. Test 03 결과

- 영상 Duration: 30.8317초
- Memo Start: 25.94초
- Ground Truth: 6.0~23.0초

| Block | 구간 | Segment IDs | Transcript |
| --- | ---: | --- | --- |
| block-0001 | 1.62~4.28초 | segment-0001 | `3번째 테스트 영상입니다.` |
| **block-0002 (선택)** | **7.52~22.26초** | segment-0002~0004 | `오늘 카페에 갔는데 제가 커피를 주문하고 자리에 앉았거든요. 그런데 한잔 이따가 보니까 제 커피가 아니라 옆사람 커피를 들고 온 거예요. 그래서 다시 카운터까지 꺼져다 줬어요.` |

| Candidate | IoU | Coverage | Start Error | End Error | Total Boundary Error |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 7.52~22.26초 | 0.8671 | 0.8671 | 1.52초 | 0.74초 | 2.26초 |

긴 이야기가 하나의 block으로 묶였다. Fixed Window 최고 IoU였던 30초의 0.6554보다 높고, Total Boundary Error도 Fixed Window 최저값 7.88초에서 2.26초로 감소했다.

## 6. Test 04 결과

- 영상 Duration: 34.2000초
- Memo Start: 30.14초
- Ground Truth: 7.0~11.0초

| Block | 구간 | Segment IDs | Transcript |
| --- | ---: | --- | --- |
| block-0001 | 0.00~3.94초 | segment-0001 | `4번째 테스트 영상입니다.` |
| **block-0002 (선택)** | **8.08~10.56초** | segment-0002 | `오, 떨어뜨릴 뻔했다.` |

| Candidate | IoU | Coverage | Start Error | End Error | Total Boundary Error |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 8.08~10.56초 | 0.6200 | 0.6200 | 1.08초 | 0.44초 | 1.52초 |

중요 발화 뒤의 긴 침묵을 건너뛰고 관련 block을 선택했다. Fixed Window 최고 IoU 0.1333과 Total Boundary Error 26.00초보다 크게 개선됐다. 다만 발화 밖의 GT 구간을 포함하지 못해 Coverage는 0.6200이다.

## 7. Test 05 결과

- 영상 Duration: 33.1000초
- Memo Start: 26.84초
- Ground Truth: 20.0~26.0초

| Block | 구간 | Segment IDs | Transcript |
| --- | ---: | --- | --- |
| block-0001 | 0.00~11.12초 | segment-0001~0002 | `마지막 테스트 영상입니다 아 탱 떨어졌다` |
| block-0002 | 16.00~18.20초 | segment-0003 | `다시 주워서 놓겠습니다` |
| **block-0003 (선택)** | **22.48~24.90초** | segment-0004 | `큰일 날 뻔 했네` |

| Candidate | IoU | Coverage | Start Error | End Error | Total Boundary Error |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 22.48~24.90초 | 0.4033 | 0.4033 | 2.48초 | 1.10초 | 3.58초 |

최신 발화는 GT 안에 있지만 transcript-only 경계가 GT의 무음·시각 구간을 놓쳐 Coverage가 0.4033에 그쳤다. Fixed Window 5초의 IoU 0.6082보다 낮고 Total Boundary Error도 2.68초에서 3.58초로 증가했다.

## 8. Fixed Window v0.2 비교

Transcript Block은 Candidate를 하나만 생성한다. Fixed Window 비교값은 자동 선택 결과가 아니라 각 Test에서 사후 확인한 최고 IoU와 최저 Total Boundary Error다.

| Test | Transcript Block Candidate | Block IoU | Block Coverage | Block Total Error | Fixed 최고 IoU | Fixed 최저 Total Error | 관찰 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Test 01 | 12.70~13.18초 | 0.0960 | 0.0960 | 4.52초 | 0.7241 | 1.60초 | 악화 |
| Test 02 | 14.00~23.80초 | 0.0000 | 0.0000 | 19.80초 | 0.1333 | 26.00초 | IoU 실패, 경계 오차만 감소 |
| Test 03 | 7.52~22.26초 | 0.8671 | 0.8671 | 2.26초 | 0.6554 | 7.88초 | 개선 |
| Test 04 | 8.08~10.56초 | 0.6200 | 0.6200 | 1.52초 | 0.1333 | 26.00초 | 개선 |
| Test 05 | 22.48~24.90초 | 0.4033 | 0.4033 | 3.58초 | 0.6082 | 2.68초 | 악화 |

Transcript Block은 Test 03과 Test 04에서 Fixed Window의 사후 최고 IoU를 넘었고 Test 01, 02, 05에서는 넘지 못했다. 평균을 계산해 일반 성능으로 주장하기에는 데이터가 5개로 너무 작으므로 Test별 결과를 유지한다.

## 9. 성공과 실패 유형

### 성공 사례

- Test 03: 여러 segment로 이어진 긴 이야기를 하나의 block으로 묶어 긴 GT를 대부분 포함했다.
- Test 04: 메모까지의 19.14초 지연과 긴 침묵에 영향받지 않고 마지막 실제 발화 block을 선택했다.

### 실패 사례

- Test 02: 관련 사건 뒤에 무관한 발화 block이 있어 최신 block 규칙이 잘못된 사건을 선택했다.
- Test 01: 짧은 반응 발화만 선택해 5초 GT 중 0.48초만 포함했다.
- Test 05: 관련 반응 발화를 선택했지만 발화 timestamp만 사용해 6초 GT 중 2.42초만 포함했다.

## 10. Transcript-only 방식의 한계와 결론

침묵 기반 block은 고정된 시간 길이 대신 실제 발화 흐름에 따라 Candidate 길이를 바꿀 수 있다. 그 결과 긴 이야기인 Test 03과 긴 메모 지연 뒤 마지막 발화가 중요 사건인 Test 04에서는 Fixed Window보다 Ground Truth에 가까워졌다.

그러나 최신 block 선택은 transcript의 의미를 보지 않는다. Test 02처럼 중요 사건 이후 다른 설명이 이어지면 과거의 올바른 block 대신 마지막 무관 block을 선택한다. 이는 silence threshold를 조정하는 것만으로 해결할 수 있는 문제가 아니다.

또한 block 경계는 음성 경계이지 영상 장면 경계가 아니다. Test 01과 Test 05에서는 올바른 반응 발화를 선택했더라도 발화 전후의 무음·시각 구간을 포함하지 못해 Coverage가 낮았다. TranscriptSegment가 없는 구간의 정확한 영상 경계를 transcript만으로 복구할 수 없다.

따라서 이번 결과는 다음 두 문제를 분리해 보여준다.

1. 여러 과거 block 중 메모가 가리키는 사건을 고르려면 시간 최신성 외의 선택 근거가 필요하다.
2. 올바른 transcript block을 선택해도 시각적 장면 경계를 정하려면 transcript 밖의 경계 정보가 필요할 수 있다.

의미 기반 선택을 검토할 근거는 Test 02에서 확인됐다. 다만 이 결과만으로 특정 LLM이나 다른 기술을 바로 선택하지 않는다. 후속 실험은 현재 deterministic 결과를 비교 기준으로 유지하고, 별도 버전에서 의미 기반 block 선택이 Test 02를 개선하면서 다른 Test를 악화시키지 않는지 평가해야 한다.
