# Visual Motion Scene Boundary Refinement Evaluation v0.1

## 1. 실험 목적

선택된 TranscriptBlock 주변의 시각적 motion signal이 발화 timestamp보다 실제 영상 장면 경계에 가까운 Candidate를 만들 수 있는지 평가한다. 의미 판단은 하지 않으며 Audio Boundary v0.1과 동일한 selected block을 고정했다.

Ground Truth는 Visual Refiner 입력에 포함하지 않았고 `REFINED` Candidate가 만들어진 뒤 기존 `CandidateEvaluator`에만 사용했다. 원본 영상은 로컬 FFmpeg로만 처리했으며 외부 API, LLM, VLM, OpenCV, NumPy, Optical Flow, FFmpeg scene score를 사용하지 않았다.

| Test | 고정 Selected Block | Original Candidate |
| --- | --- | ---: |
| Test 01 | block-0002 | 12.70~13.18 |
| Test 02 | block-0001 | 3.04~10.96 |
| Test 03 | block-0002 | 7.52~22.26 |
| Test 04 | block-0002 | 8.08~10.56 |
| Test 05 | block-0003 | 22.48~24.90 |

## 2. 평가 전에 고정한 Config와 성공 기준

| 설정 | 값 |
| --- | ---: |
| sample_fps | 5 |
| frame_width | 160 px |
| frame_height | 원본 종횡비 유지, 짝수 높이 |
| smoothing_window_frames | 3 |
| threshold | median + 3 × median_absolute_deviation |
| minimum_motion_duration_seconds | 0.4초 |
| maximum_quiet_gap_seconds | 0.6초 |

사전 성공 기준은 다음과 같이 고정했다.

1. Test별 config 예외와 invalid interval이 0건이고 동일 입력에서 결과가 재현된다.
2. Test 01 또는 05 중 하나 이상에서 Raw 대비 IoU와 Coverage가 함께 개선된다.
3. Test 02에서 잘못된 확정 Candidate로 Raw IoU 0.4975를 크게 훼손하지 않는다.
4. 성공 Candidate의 median IoU가 대응 Raw보다 상승한다.
5. 성공 Candidate의 median Total Boundary Error가 감소한다.
6. 최소 3/5 Test에서 `REFINED`다.
7. `NO_SIGNAL`과 `AMBIGUOUS_SIGNAL`을 fallback 없이 그대로 기록한다.

## 3. Frame 추출과 Motion 계산

FFmpeg는 shell 없이 인자 리스트로 실행했으며 각 Test의 local search range만 decode했다.

```text
ffmpeg -v error -nostdin
  -ss <search_start> -t <search_duration>
  -i <source>
  -map 0:v:0 -an -sn -dn
  -vf fps=5,scale=160:-2:flags=bicubic,format=gray
  -f image2pipe -vcodec pgm pipe:1
```

PGM frame bytes는 Python 표준 라이브러리만으로 파싱했다. 인접 두 frame의 motion magnitude는 다음과 같다.

```text
score(t) = sum(abs(frame_t[p] - frame_t-1[p]))
           / (pixel_count × 255)
```

score에 3-frame 중앙값 smoothing을 적용한 뒤 전체 local range의 median과 `median_absolute_deviation = median(abs(score - median))`을 계산했다. effective threshold는 `median + 3 × median_absolute_deviation`이다. MAD가 0이면 완전히 정적인 score가 모두 active가 되지 않도록 `nextafter(median, +inf)`를 사용한다.

Threshold 이상 score를 interval로 묶고 0.4초 미만 spike를 제거했으며 0.6초 이하 quiet gap을 병합했다. Selected block과 겹치는 interval이 정확히 하나일 때만 `REFINED`, 여러 개면 `AMBIGUOUS_SIGNAL`, 없으면 `NO_SIGNAL`로 기록했다. 자동 fallback은 없다.

## 4. Test 01

- Ground Truth: 10.0~15.0초
- Original block: 12.70~13.18초
- Search range: 9.90~15.80초
- Frame size/count: 160×90, motion score 29개
- Score min/mean/max: 0.002611 / 0.017154 / 0.056204
- Median / median absolute deviation / threshold: 0.014839 / 0.009026 / 0.041918
- Processing latency: 10.2137초
- Status: `NO_SIGNAL`

| Activity interval | Peak | Mean | Block overlap |
| ---: | ---: | ---: | --- |
| 10.10~10.70 | 0.056204 | 0.052538 | 아니오 |

GT 시작 부근의 motion은 검출됐지만 reaction block과 연결되지 않았다. Candidate와 평가 지표는 만들지 않았다.

## 5. Test 02

- Ground Truth: 7.0~11.0초
- Original block: 3.04~10.96초
- Search range: 0.00~14.00초
- Frame size/count: 160×284, motion score 69개
- Score min/mean/max: 0.037422 / 0.092117 / 0.198067
- Median / median absolute deviation / threshold: 0.084502 / 0.020144 / 0.144933
- Processing latency: 17.7100초
- Status: `NO_SIGNAL`

| Activity interval | Peak | Mean | Block overlap |
| ---: | ---: | ---: | --- |
| 0.00~1.00 | 0.198067 | 0.169335 | 아니오 |

선택 block 내부의 낙하·반응 구간은 local threshold를 넘는 0.4초 이상 episode가 되지 않았다. 잘못된 Candidate를 생성하지 않아 Raw IoU를 훼손하지는 않았지만 경계 개선도 하지 못했다.

## 6. Test 03

- Ground Truth: 6.0~23.0초
- Original block: 7.52~22.26초
- Search range: 4.28~25.94초
- Frame size/count: 160×284, motion score 107개
- Score min/mean/max: 0.024621 / 0.072341 / 0.140036
- Median / median absolute deviation / threshold: 0.067706 / 0.014611 / 0.111540
- Processing latency: 20.2737초
- Status: `REFINED`

| Activity interval | Peak | Mean | Block overlap | 선택 |
| ---: | ---: | ---: | --- | --- |
| 17.48~19.28 | 0.140036 | 0.132693 | 예 | 선택 |
| 22.48~23.08 | 0.119002 | 0.118723 | 아니오 | |

- Refined Candidate: 17.48~19.28초
- IoU: 0.1059
- Coverage: 0.1059
- Start Error: 11.48초
- End Error: 3.72초
- Total Boundary Error: 15.20초

| 비교 | IoU | Coverage | Total Error |
| --- | ---: | ---: | ---: |
| Raw block | 0.8671 | 0.8671 | 2.26 |
| Audio v0.1 | 0.3224 | 0.3224 | 11.52 |
| Visual v0.1 | 0.1059 | 0.1059 | 15.20 |

긴 이야기 중 가장 강한 motion episode만 남아 Raw와 Audio보다 모두 악화됐다.

## 7. Test 04

- Ground Truth: 7.0~11.0초
- Original block: 8.08~10.56초
- Search range: 3.94~30.14초
- Frame size/count: 160×284, motion score 130개
- Score min/mean/max: 0.020747 / 0.066475 / 0.121192
- Median / median absolute deviation / threshold: 0.062781 / 0.008437 / 0.088093
- Processing latency: 23.3305초
- Status: `REFINED`

| Activity interval | Peak | Mean | Block overlap | 선택 |
| ---: | ---: | ---: | --- | --- |
| 4.14~4.54 | 0.097500 | 0.097500 | 아니오 | |
| 5.54~6.54 | 0.102780 | 0.100290 | 아니오 | |
| 9.94~10.54 | 0.094355 | 0.093752 | 예 | 선택 |
| 15.14~16.34 | 0.106603 | 0.097272 | 아니오 | |
| 17.74~18.54 | 0.121192 | 0.114027 | 아니오 | |

- Refined Candidate: 9.94~10.54초
- IoU: 0.1500
- Coverage: 0.1500
- Start Error: 2.94초
- End Error: 0.46초
- Total Boundary Error: 3.40초

| 비교 | IoU | Coverage | Total Error |
| --- | ---: | ---: | ---: |
| Raw block | 0.6200 | 0.6200 | 1.52 |
| Audio v0.1 | 0.3800 | 0.3800 | 2.48 |
| Visual v0.1 | 0.1500 | 0.1500 | 3.40 |

Reaction block 안의 일부 강한 움직임만 남아 장면 시작과 발화 앞부분을 놓쳤다.

## 8. Test 05

- Ground Truth: 20.0~26.0초
- Original block: 22.48~24.90초
- Search range: 18.20~26.84초
- Frame size/count: 160×284, motion score 42개
- Score min/mean/max: 0.025941 / 0.092154 / 0.198251
- Median / median absolute deviation / threshold: 0.073022 / 0.039158 / 0.190495
- Processing latency: 8.2218초
- Status: `NO_SIGNAL`
- Activity intervals: 없음

최대 score 0.198251은 threshold를 넘었지만 0.4초 이상 지속되는 episode가 아니어서 spike 제거 단계에서 제외됐다. Candidate와 평가 지표는 만들지 않았다.

## 9. Refinement Yield와 전체 비교

```text
refinement_yield = REFINED Test 수 / 전체 Test 수
                 = 2 / 5
                 = 40%
```

`NO_SIGNAL`은 Test 01, 02, 05에서 3건이었고 `AMBIGUOUS_SIGNAL`은 실제 eval에서 0건이었다. 실패 결과를 Fixed Window나 Raw block으로 대체하지 않았다.

Fixed Window 수치는 시스템의 자동 선택 결과가 아니라 Ground Truth를 본 사후 oracle 최고 IoU다.

| Test | Raw IoU / Total Error | Audio IoU / Total Error | Visual status | Visual IoU / Total Error | Fixed oracle IoU |
| --- | ---: | ---: | --- | ---: | ---: |
| 01 | 0.0960 / 4.52 | 0.1200 / 4.40 | NO_SIGNAL | N/A | 0.7241 |
| 02 | 0.4975 / 4.00 | 0.0000 / 7.82 | NO_SIGNAL | N/A | 0.1333 |
| 03 | 0.8671 / 2.26 | 0.3224 / 11.52 | REFINED | 0.1059 / 15.20 | 0.6554 |
| 04 | 0.6200 / 1.52 | 0.3800 / 2.48 | REFINED | 0.1500 / 3.40 | 0.1333 |
| 05 | 0.4033 / 3.58 | 0.4400 / 3.36 | NO_SIGNAL | N/A | 0.6082 |

성공 Candidate가 생성된 Test 03·04만 비교하면:

| 지표 | 대응 Raw | Visual v0.1 |
| --- | ---: | ---: |
| Median IoU | 0.7435 | 0.1279 |
| Median Total Boundary Error | 1.89초 | 9.30초 |

성공 Test만의 지표가 전체 성능을 과장하지 않도록 40% yield와 3건의 `NO_SIGNAL`을 함께 기록한다.

## 10. 사전 성공 기준 판정

- Test별 config 예외 0건: **통과**
- Invalid interval 0건: **통과**
- 동일 입력 재현: **통과**
- Test 01 또는 05 IoU·Coverage 공동 개선: **실패** — 둘 다 `NO_SIGNAL`
- Test 02의 잘못된 확정 Candidate 방지: **통과** — `NO_SIGNAL`로 기록
- 성공 Candidate median IoU 상승: **실패** — 0.7435에서 0.1279로 하락
- 성공 Candidate median Total Error 감소: **실패** — 1.89초에서 9.30초로 증가
- 최소 3/5 `REFINED`: **실패** — 2/5
- 신호 없음/모호함을 fallback 없이 기록: **통과**

따라서 Visual Motion Boundary v0.1 전체 성공 기준은 **미달**이다.

## 11. False Positive, 한계와 VLM 검토 근거

Test 03·04에서는 selected block과 겹친 강한 motion이 실제 장면 전체가 아니라 긴 이야기나 reaction 내부의 일부 동작이었다. Motion magnitude는 움직임의 존재와 세기는 측정하지만 물체 낙하, 일상적인 몸짓, 카메라 움직임 중 무엇이 사용자가 살리고 싶은 사건인지 판단하지 못한다.

Test 01에서는 GT 시작 부근의 motion episode를 실제로 검출했지만 selected block과 시간적으로 분리되어 있어 연결하지 못했다. Test 05에서는 강한 단발 motion이 있었지만 공통 최소 지속시간 정책으로 제거됐다. Threshold나 지속시간을 Test별로 바꾸면 결과를 개선할 수 있어 보여도 v0.1 과적합이므로 변경하지 않았다.

이번 결과는 deterministic visual motion만으로 부족하다는 근거를 만든다.

1. Refinement yield가 40%에 그쳤다.
2. 생성된 Candidate 두 개 모두 Raw보다 악화됐다.
3. 중요한 motion이 발화 block과 떨어져 있으면 관련성을 연결할 수 없었다.
4. 강한 motion이 있어도 그것이 사건인지 일상 동작인지 구분할 수 없었다.
5. 긴 이야기에서는 일부 강한 동작만 선택해 장면을 과도하게 축소했다.

따라서 후속 VLM Spike를 검토할 근거는 생겼다. 다만 VLM이 자유 timestamp를 생성하게 하기보다 deterministic code가 visual episode 또는 boundary proposal ID를 만들고 VLM은 관련 proposal ID만 선택하며, 일반 Python validator가 timestamp와 영상 범위를 검증하는 구조가 적절하다. 데이터가 5개뿐이므로 일반 성능을 주장할 수는 없다.

## 12. 의도적으로 하지 않은 것

- Gemini/LLM/VLM 호출 또는 구현
- Embedding, OpenCV, NumPy, Optical Flow, FFmpeg scene score 결합
- Test별 threshold, duration, gap 변경
- Audio Boundary, STT, Memo Detector, Transcript Block, Clip Renderer 변경
- Selected block 또는 Ground Truth 변경
- `NO_SIGNAL` 자동 fallback
- 결과 확인 후 v0.1 config나 정책 수정
- API 엔드포인트 추가
