# MVP-07B — STT 환경 재현성과 실제 영상 품질 문제 원인 분석

분석 기준: `main` / `b9ffb25ed2d2cf6d227d667084fbfaeaa40ec8b0`, 2026-10-24. 입력과 산출물의 경로·해시·실행 시간은 [MVP-07A 실제 영상 검증](mvp-07a-real-video-validation.md)에 기록돼 있다. 이번 단계는 기존 P1-S01 실행 결과, 저장된 DB 데이터, 로컬 WAV 재현, 코드 추적만 수행했다. 제품 코드·의존성·평가 계약·GT·Manifest·원본 영상·렌더 결과는 변경하지 않았다. 외부 LLM/VLM API는 호출하지 않았다.

## 1. STT — faster-whisper와 PyAV 호환성 (P0)

**관찰·재현.** 기본 가상환경은 `faster-whisper==1.2.1`, `av==19.0.2`다. 첫 실제 영상 실행은 PROBE·AUDIO_EXTRACTION 완료 후 STT가 `STT_FAILED`가 됐다. 같은 실행에서 추출한 WAV를 `transcribe_audio(..., word_timestamps=True)`로 다시 처리하면 다음 호출 경로에서 실패한다.

```text
backend/app/services/stt_service.py:77  stt_model.transcribe(...)
faster_whisper/transcribe.py:876       decode_audio(...)
faster_whisper/audio.py:46            av.open(input_file, mode="r", metadata_errors="ignore")
av/container/core.py:479             TypeError: open() got an unexpected keyword argument 'metadata_errors'
backend/app/services/stt_service.py:89  STTError(...), 위 TypeError가 원인으로 연결됨
```

**원인.** `requirements.txt`는 faster-whisper 1.2.1을 직접 고정하지만 PyAV는 지정하지 않는다. lock 파일도 없다. 설치된 faster-whisper 메타데이터의 요구 범위는 `av>=11`이라 PyAV 19가 설치 가능하다. PyAV 19가 `metadata_errors` 인자를 제거한 반면 현재 faster-whisper 1.2.1의 오디오 디코더는 그 인자를 전달한다. [PyAV 변경 기록](https://github.com/PyAV-Org/PyAV/releases), [faster-whisper 업스트림 이슈](https://github.com/SYSTRAN/faster-whisper/issues/1589).

**확정·미검증.** `av==18.1.0`을 무시되는 `evaluation/tmp/` 경로에 격리 설치하고 한 프로세스의 `PYTHONPATH`에만 적용하자 같은 실제 입력의 STT가 성공했다. 이 조합에서 `pip check`는 선언된 의존성 충돌을 찾지 못했다. 현재 설치 패키지 중 PyAV를 직접 요구하는 것은 faster-whisper뿐이다. 다른 Python/OS, 향후 패키지 버전 및 실제 장시간 영상에서의 호환성은 검증하지 않았다. PyAV 19 대응 업스트림 개발 코드가 있어도 배포 버전의 동작은 별도로 확인해야 한다.

**향후 해결·회귀.** 승인 후 단기 방안은 호환 범위 `av>=11,<19` 또는 검증한 `av==18.1.0` 명시와 전이 의존성 재현 방법 마련이다. 다른 방안은 PyAV 19를 지원하는 faster-whisper 배포 버전을 확인하고 함께 업그레이드하는 것이다. 어느 쪽이든 깨끗한 Windows 환경의 설치·`pip check`·짧은 WAV 디코딩·단어 시각·소스 처리 API를 검증하고, 지원 OS에서도 확인해야 한다. 단순 PyAV 버전 명시만으로 환경 전체가 고정되지는 않는다. 영향 범위는 STT 이후 메모 검출, 전사 Evidence, 자막이다. **의존성 변경은 아직 없다.**

## 2. SceneCandidate — Evidence 교집합에 따른 짧은 구간 (P1)

**관찰.** P1-S01의 촬영자 확인 사건 구간은 4.00~6.22초다. 저장된 자동 발견 후보 5개는 다음과 같다. `SceneCandidate.confidence`와 각 `SceneEvidence.confidence`는 모두 `null`이며 후보 점수나 자동 추천 순위는 없다. Evidence payload의 음량·프레임 차이 수치는 후보 점수가 아니다.

| 후보 구간(초) | promotion 규칙 | 경계를 만든 두 Evidence |
| --- | --- | --- |
| 2.44~2.62 | `AUDIO_PLUS_VISUAL_ACTIVITY` | 오디오 2.44~2.62 ∩ 영상 2.40~2.80 |
| 4.08~4.60 | `AUDIO_PLUS_VISUAL_ACTIVITY` | 오디오 4.08~4.84 ∩ 영상 3.80~4.60 |
| 4.64~4.84 | `TRANSCRIPT_STRUCTURE_PLUS_AUDIO` | 전사 4.64~6.12 ∩ 오디오 4.08~4.84 |
| **5.54~6.12** | `TRANSCRIPT_STRUCTURE_PLUS_AUDIO` | 전사 4.64~6.12 ∩ 오디오 5.54~6.48 |
| 8.86~11.00 | `TRANSCRIPT_STRUCTURE_PLUS_AUDIO` | 전사 8.44~11.00 ∩ 오디오 8.86~11.26 |

4.6~13.498초 `STATIC_INTERVAL`은 뒤의 세 후보와 겹쳐 부착된 QUALITY Evidence다. promotion의 입력 쌍이나 점수가 아니다. 8.86~11.00초 후보는 이후 발화한 AI 메모와 겹친다.

**원인.** `backend/app/services/autonomous_discovery.py`의 `build_promotion_manifest()`는 허용된 Evidence 두 개가 겹칠 때 **교집합 구간**을 후보로 만든다. 4.64~6.12초 전사는 4.84~5.54초의 오디오 활동 공백으로 두 후보로 분리된다. 영상 활동은 4.60초에 끝나 전사 시작 4.64초와 겹치지 않는다. 반응 어휘 설정에는 `아 뭐야`가 없어 이번 실행의 `TRANSCRIPT_REACTION_CUE`는 없다. 오디오는 WAV RMS 활동이며 의미를 분류한 오디오 이벤트가 아니다. STT 호출은 VAD 필터를 지정하지 않았고 설치된 faster-whisper의 기본 `vad_filter`는 `False`다. 영상 Evidence는 프레임 차이다. MVP-07A 검증 스크립트가 촬영자 확인 구간과 **가장 길게 겹치는 후보**를 골라 5.54~6.12초를 편집 계획에 넣었다. 제품이 이 후보를 자동 추천한 결과가 아니다.

**확정·미검증.** 위 경계와 분리 원인은 코드·DB Evidence로 확인했다. 0.58초 영상이 사건 전체를 충분히 표현한다는 품질 주장은 성립하지 않는다. GT가 미동결이므로 정량 recall·tIoU 합격은 선언하지 않았다.

**향후 해결·회귀.** 기존 후보와 Evidence를 보존하면서 인접 후보의 사건 단위 연결 또는 넓은 편집 제안을 별도 실험으로 비교한다. 오디오 공백·영상 연속성뿐 아니라 다른 사건이나 메모를 잘못 합치는 경우를 평가해야 한다. P1~P3 계약·GT·Manifest와 임계값을 관찰 결과에 맞춰 바꾸지 않는다. 후보 교집합·분리·중복 제거의 결정적 테스트와 실제 영상에서 사건 누락·잘못된 합침·메모 포함 여부의 평가가 필요하다. 영향 범위는 후보 경계, 편집 선택, 렌더 길이, 자막 매핑이다. **후보 생성 규칙은 수정하지 않았다.**

## 3. STT 단어 공백과 SRT 결합 (P2)

**관찰·재현.** 호환 PyAV로 같은 로컬 WAV를 재전사한 문장·구간·단어 시각은 DB 저장값과 일치했다. 저장된 문장은 `아 뭐야 에이아이아 방금 장면 살려줘`, 첫 구간은 4.64~6.12초 `아 뭐야`다. 첫 단어 둘의 저장 텍스트는 `아`, `뭐야`이다. `final.srt`의 원문은 다음과 같다.

```srt
1
00:00:00,000 --> 00:00:00,566
아뭐야
```

**원인.** faster-whisper의 원래 단어 문자열은 `' 아'`, `' 뭐야'`처럼 앞 공백을 포함했다. `backend/app/services/stt_service.py`의 `_parse_word()`가 `.strip()`으로 이를 지우고, `source_processing.py`의 `_new_transcript()`가 제거된 단어를 보존한다. `project_subtitles.py`의 `map_subtitle_cues()`는 선택 단어를 구분자 없이 `"".join(...)`으로 연결한다. 따라서 SRT 공백 소실은 **단어 파싱과 자막 결합의 조합**에서 발생했다. 저장된 segment 문장에는 공백이 남아 있어 전체 전사 문장은 손상되지 않았다.

**정책과 구분.** 촬영자 기록 `어 뭐야`에 비해 STT가 `아 뭐야`로 인식한 첫 음절 차이는 자막 공백 문제와 별개의 STT 인식 문제다. 현재 자막 정책은 선택 구간과 반열린 구간으로 겹치는 단어를 잘라 포함하고, 단어가 없으면 segment 전체가 선택됐을 때만 문장을 사용한다. 출력 클립 길이에 맞춰 시각을 비례 변환하고 밀리초 반올림을 적용한다. 저장된 문장부호는 유지하지만 새 문장부호를 추정하지 않으며, 여러 공백·개행을 한 칸으로 정리하고 SRT 시간 화살표를 치환한다. 이번 선택 구간은 첫 단어의 끝부분만 포함하지만 단어 전체 `아`가 자막에 표시된다. 이 부분 단어 정책의 적절성은 미검증이다.

**향후 해결·회귀.** 원본 문장·단어 시각을 수정하지 않고 자막 생성 시 공백 복원 규칙을 명시한다. 모델 출력의 앞 공백이 있는 단어와 이미 공백이 제거된 DB 단어, 문장부호, 한국어·영어 혼합, 부분 단어·클립 경계, 반복 클립, 시간 반올림, SRT 삽입 방어를 회귀 검증해야 한다. 기존 자막 테스트의 앞 공백이 보존된 입력만으로는 이번 저장 경로의 조합을 포착하지 못한다. 영향 범위는 SRT와 하드 자막 표시이며 기본 MP4와 원본 전사는 보존해야 한다. **자막 코드와 기존 산출물은 수정하지 않았다.**

## 다음 작업의 경계

우선순위는 STT 설치 재현성(P0) → 사건 단위 후보 품질 실험(P1) → 자막 공백 정책·수정(P2)이다. 구현 순서는 승인과 평가 근거에 따라 조정한다. 이번 기록은 원인 분석이며 수정 완료나 실제 영상 품질 합격을 뜻하지 않는다. 향후 변경 시 해결 커밋, 재현 환경, 수정 전후 테스트, 남은 한계를 이 기록 또는 후속 handoff에 연결한다.
