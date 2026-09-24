# Audio Activity Scene Boundary Refinement Evaluation v0.1

## 1. 실험 목적

의미 기반 또는 최신 TranscriptBlock 선택 이후에도 음성 timestamp와 실제 영상 장면 경계가 다르다는 문제를 분리해 평가한다. 선택된 block을 anchor로 고정하고, 로컬 16 kHz mono PCM16 WAV의 audio activity만으로 경계를 확장하거나 축소했다.

Ground Truth는 refiner 입력에 포함하지 않았으며 Candidate 생성 후 기존 `CandidateEvaluator`에만 사용했다. Gemini/LLM, VLM, 영상 프레임, Fixed Window fallback은 사용하지 않았다. block 선택은 평가 전에 다음과 같이 고정했고 결과를 본 뒤 변경하지 않았다.

| Test | 고정 Selected Block | Original Candidate |
| --- | --- | ---: |
| Test 01 | block-0002 | 12.70~13.18 |
| Test 02 | block-0001 | 3.04~10.96 |
| Test 03 | block-0002 | 7.52~22.26 |
| Test 04 | block-0002 | 8.08~10.56 |
| Test 05 | block-0003 | 22.48~24.90 |

## 2. 평가 전 고정한 Config와 성공 기준

모든 Test에 동일한 `audio-boundary-v0.1` 설정을 사용했다.

| 항목 | 값 | 선택 이유 |
| --- | ---: | --- |
| frame_duration_ms | 20 ms | 짧은 충격과 발화 onset을 보면서 frame 노이즈를 과도하게 키우지 않는 일반적인 짧은 분석 단위 |
| energy_margin_db | 10 dB | 녹음마다 다른 바닥 소음보다 명확히 높은 frame만 activity로 제한 |
| minimum_activity_duration_seconds | 0.08초 | 80 ms 미만 클릭성 spike 제거 |
| maximum_quiet_gap_seconds | 0.25초 | 음절·짧은 호흡 사이를 한 episode로 병합 |

평가 전에 고정한 성공 기준은 다음과 같다.

1. Test 01 또는 05 중 적어도 하나에서 raw block 대비 IoU와 Coverage가 함께 개선된다.
2. Test 02 raw IoU 0.4975를 크게 훼손하지 않는다.
3. 평가 가능한 Test의 median IoU가 상승한다.
4. median Total Boundary Error가 감소한다.
5. invalid interval과 Test별 config 예외가 없고 동일 입력에서 결과가 재현된다.

## 3. Audio Activity 계산과 선택 규칙

1. 이전 block 종료 또는 0초부터 다음 block 시작과 memo 시작 중 빠른 시점까지를 로컬 탐색 범위로 사용한다. 범위는 선택 block 전체를 반드시 포함하고 영상 범위로 clip한다.
2. 표준 라이브러리 `wave`와 `array`로 mono PCM16 sample을 읽고 20 ms frame별 RMS와 dBFS를 계산한다.
3. 로컬 frame 에너지를 정렬하고 낮은 에너지 절반의 median을 noise floor로 사용한다. 무음 frame은 -96 dBFS로 제한해 계산한다.
4. `noise floor + 10 dB` 이상 frame을 activity로 본다.
5. 250 ms 이하 quiet gap을 병합하고 80 ms 미만 episode를 제거한다.
6. 선택 block과 겹치는 episode 중 block과의 겹침 길이가 가장 큰 하나를 선택한다. 동률이면 episode 길이, 더 빠른 시작 순으로 결정한다.
7. 선택 episode가 없으면 실패하며 Fixed Window로 fallback하지 않는다.

## 4. Test 01

- Ground Truth: 10.0~15.0초
- Original block: 12.70~13.18초
- Local search: 9.90~15.80초
- Noise floor / threshold: -53.3648 / -43.3648 dBFS
- Processing latency: 0.0037초
- Refinement: 성공

| Activity interval | Peak / Mean dBFS | Block overlap | 선택 |
| ---: | ---: | --- | --- |
| 9.90~10.20 | -32.23 / -34.97 | 아니오 | |
| 10.80~10.96 | -41.05 / -41.73 | 아니오 | |
| 11.68~12.04 | -18.54 / -31.59 | 아니오 | |
| 12.76~13.36 | -20.54 / -31.28 | 예 | 선택 |
| 14.06~14.16 | -40.51 / -42.10 | 아니오 | |
| 15.48~15.64 | -33.31 / -37.58 | 아니오 | |

- Refined: 12.76~13.36초
- Adjustment: start +0.06초 / end +0.18초
- Evidence: `ENERGY_ONSET` / `ENERGY_OFFSET`

| Candidate | IoU | Coverage | Start Error | End Error | Total Error |
| --- | ---: | ---: | ---: | ---: | ---: |
| Raw block | 0.0960 | 0.0960 | 2.70 | 1.82 | 4.52 |
| Audio refined | 0.1200 | 0.1200 | 2.76 | 1.64 | 4.40 |

IoU와 Coverage는 함께 소폭 개선됐지만, 사건 구간으로 보이는 9.90~12.04초 및 14초 이후 activity는 reaction episode와 250 ms 이내로 연결되지 않아 대부분 복구하지 못했다.

## 5. Test 02

- Ground Truth: 7.0~11.0초
- Original block: 3.04~10.96초
- Local search: 0.00~14.00초
- Noise floor / threshold: -68.9049 / -58.9049 dBFS
- Processing latency: 0.0067초
- Refinement: 성공했으나 평가 실패

| Activity interval | Peak / Mean dBFS | Block overlap | 선택 |
| ---: | ---: | --- | --- |
| 0.22~0.88 | -50.76 / -55.80 | 아니오 | |
| 3.86~6.32 | -22.33 / -35.35 | 예 | 선택 |
| 6.80~7.16 | -51.53 / -55.64 | 예 | |
| 8.12~8.40 | -22.57 / -41.13 | 예 | |
| 9.40~11.16 | -21.31 / -30.79 | 예 | |
| 12.76~12.92 | -53.72 / -55.40 | 아니오 | |

- Refined: 3.86~6.32초
- Adjustment: start +0.82초 / end -4.64초
- Evidence: `ENERGY_ONSET` / `ENERGY_OFFSET`

| Candidate | IoU | Coverage | Start Error | End Error | Total Error |
| --- | ---: | ---: | ---: | ---: | ---: |
| Raw block | 0.4975 | 0.9900 | 3.96 | 0.04 | 4.00 |
| Audio refined | 0.0000 | 0.0000 | 3.14 | 4.68 | 7.82 |

가장 긴 겹침 episode가 도입 발화였고 실제 사건 반응에 가까운 9.40~11.16초를 선택하지 못했다. Audio energy만으로 여러 발화 episode의 의미적 관련성을 판단할 수 없음을 보여준다.

## 6. Test 03

- Ground Truth: 6.0~23.0초
- Original block: 7.52~22.26초
- Local search: 4.28~25.94초
- Noise floor / threshold: -62.7934 / -52.7934 dBFS
- Processing latency: 0.0106초
- Refinement: 성공했으나 장기 발화 분절

| Activity interval | Peak / Mean dBFS | Block overlap | 선택 |
| ---: | ---: | --- | --- |
| 4.28~4.38 | -34.18 / -42.58 | 아니오 | |
| 7.56~12.18 | -21.62 / -33.48 | 예 | |
| 12.78~18.26 | -20.65 / -33.35 | 예 | 선택 |
| 19.22~22.24 | -22.23 / -35.84 | 예 | |

- Refined: 12.78~18.26초
- Adjustment: start +5.26초 / end -4.00초
- Evidence: `ENERGY_ONSET` / `ENERGY_OFFSET`

| Candidate | IoU | Coverage | Start Error | End Error | Total Error |
| --- | ---: | ---: | ---: | ---: | ---: |
| Raw block | 0.8671 | 0.8671 | 1.52 | 0.74 | 2.26 |
| Audio refined | 0.3224 | 0.3224 | 6.78 | 4.74 | 11.52 |

한 이야기 안의 0.60초와 0.96초 휴지가 episode를 나눴다. 단일 episode 선택은 긴 장면을 크게 축소했다.

## 7. Test 04

- Ground Truth: 7.0~11.0초
- Original block: 8.08~10.56초
- Local search: 3.94~30.14초
- Noise floor / threshold: -66.3954 / -56.3954 dBFS
- Processing latency: 0.0122초
- Refinement: 성공했으나 악화

| Activity interval | Peak / Mean dBFS | Block overlap | 선택 |
| ---: | ---: | --- | --- |
| 3.94~4.06 | -38.72 / -49.88 | 아니오 | |
| 8.44~8.74 | -22.54 / -38.61 | 예 | |
| 9.26~10.78 | -19.68 / -33.62 | 예 | 선택 |
| 16.36~17.76 | -17.72 / -39.92 | 아니오 | |
| 18.14~19.50 | -18.32 / -45.15 | 아니오 | |
| 19.76~19.84 | -53.72 / -55.28 | 아니오 | |
| 20.62~20.84 | -29.44 / -41.65 | 아니오 | |
| 21.90~22.16 | -39.57 / -47.96 | 아니오 | |
| 23.06~23.28 | -32.24 / -41.43 | 아니오 | |
| 24.86~25.64 | -51.63 / -54.06 | 아니오 | |
| 26.58~27.78 | -27.43 / -47.17 | 아니오 | |
| 28.28~28.46 | -49.73 / -52.90 | 아니오 | |
| 29.22~29.54 | -36.48 / -49.39 | 아니오 | |

- Refined: 9.26~10.78초
- Adjustment: start +1.18초 / end +0.22초
- Evidence: `ENERGY_ONSET` / `ENERGY_OFFSET`

| Candidate | IoU | Coverage | Start Error | End Error | Total Error |
| --- | ---: | ---: | ---: | ---: | ---: |
| Raw block | 0.6200 | 0.6200 | 1.08 | 0.44 | 1.52 |
| Audio refined | 0.3800 | 0.3800 | 2.26 | 0.22 | 2.48 |

reaction 앞부분이 별도 짧은 episode로 분리되어 start가 늦어졌다. 뒤쪽 경계는 개선됐지만 전체 Coverage와 IoU는 악화됐다.

## 8. Test 05

- Ground Truth: 20.0~26.0초
- Original block: 22.48~24.90초
- Local search: 18.20~26.84초
- Noise floor / threshold: -60.9844 / -50.9844 dBFS
- Processing latency: 0.0042초
- Refinement: 성공

| Activity interval | Peak / Mean dBFS | Block overlap | 선택 |
| ---: | ---: | --- | --- |
| 18.20~18.48 | -31.13 / -37.93 | 아니오 | |
| 22.26~24.90 | -20.97 / -29.54 | 예 | 선택 |

- Refined: 22.26~24.90초
- Adjustment: start -0.22초 / end 0.00초
- Evidence: `ENERGY_ONSET` / `SPEECH_ACTIVITY`

| Candidate | IoU | Coverage | Start Error | End Error | Total Error |
| --- | ---: | ---: | ---: | ---: | ---: |
| Raw block | 0.4033 | 0.4033 | 2.48 | 1.10 | 3.58 |
| Audio refined | 0.4400 | 0.4400 | 2.26 | 1.10 | 3.36 |

발화 onset 앞 0.22초는 복구했지만 20초 부근 사건과 24.90~26.0초 시각 구간은 연결된 audio activity가 없어 복구하지 못했다.

## 9. 전체 비교와 성공 기준 판정

Fixed Window 값은 자동 선택 결과가 아니라 Ground Truth를 본 사후 oracle 참고치다.

| Test | Raw IoU / Coverage / Total Error | Refined IoU / Coverage / Total Error | Fixed Window oracle 최고 IoU | 변화 |
| --- | ---: | ---: | ---: | --- |
| 01 | 0.0960 / 0.0960 / 4.52 | 0.1200 / 0.1200 / 4.40 | 0.7241 | 소폭 개선 |
| 02 | 0.4975 / 0.9900 / 4.00 | 0.0000 / 0.0000 / 7.82 | 0.1333 | 크게 악화 |
| 03 | 0.8671 / 0.8671 / 2.26 | 0.3224 / 0.3224 / 11.52 | 0.6554 | 크게 악화 |
| 04 | 0.6200 / 0.6200 / 1.52 | 0.3800 / 0.3800 / 2.48 | 0.1333 | 악화 |
| 05 | 0.4033 / 0.4033 / 3.58 | 0.4400 / 0.4400 / 3.36 | 0.6082 | 소폭 개선 |

| 집계 | Raw | Audio refined | 판정 |
| --- | ---: | ---: | --- |
| Median IoU | 0.4975 | 0.3224 | 하락, 실패 |
| Median Coverage | 0.6200 | 0.3224 | 하락 |
| Median Total Boundary Error | 3.58초 | 4.40초 | 증가, 실패 |

- Test 01/05 공동 개선: **통과** — 두 Test 모두 IoU와 Coverage가 함께 개선됐다.
- Test 02 보존: **실패** — IoU 0.4975에서 0.0000으로 하락했다.
- Median IoU 상승: **실패**.
- Median Total Boundary Error 감소: **실패**.
- 유효 구간·공통 config·재현성: **통과** — 5개 모두 유효 구간이며 Test별 예외가 없고 단위 테스트에서 동일 입력 결과가 일치했다.

따라서 v0.1 전체 성공 기준은 **미달**이다.

## 10. 실패 분석과 다음 기술 판단 근거

Audio activity는 Test 01과 05에서 transcript timestamp가 잘라낸 발화 onset/offset 일부를 찾는 데 유효했다. 그러나 개선 폭은 0.18~0.22초 수준이며 실제 시각적 사건 전체를 복구하지 못했다.

Test 02와 03은 activity episode가 여러 개일 때 에너지 크기·길이만으로 어떤 episode가 사건 의미와 연결되는지 알 수 없음을 보여준다. Test 04도 reaction 발화 내부의 휴지가 경계를 분리해 앞부분을 잃었다. 이는 threshold만의 문제가 아니라 “여러 episode 중 무엇이 같은 장면인가”라는 의미 및 시각 경계 문제다.

이 결과는 visual signal 검토의 근거를 만든다. 특히 음성이 없거나 audio episode와 분리된 물체 낙하·손동작·위험 상황의 시작과 종료는 waveform만으로 확인할 수 없다. 다만 이 5개 결과만으로 VLM을 즉시 채택하지는 않는다. 다음 실험에서는 동일한 고정 block과 평가 지표를 유지한 채 shot/프레임 변화 같은 deterministic visual boundary가 먼저 개선 가능한지 비교하고, 그것도 연속 촬영 사건에서 실패할 때 VLM을 검토하는 순서가 타당하다.

## 11. 의도적으로 하지 않은 것

- Gemini/LLM, VLM, Embedding, Optical Flow, Shot Detection 호출 또는 구현
- Test별 parameter, block 선택, Ground Truth 변경
- Fixed Window, STT, Memo Detector, CandidateEvaluator, Clip Renderer 변경
- 결과를 본 뒤 v0.1 config 또는 episode 선택 규칙 수정
- activity 실패 시 자동 fallback
- API 엔드포인트 추가
