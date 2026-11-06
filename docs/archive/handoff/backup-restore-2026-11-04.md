# 사용자 데이터 백업·격리 복원 검증 — 2026-11-04

P0 안정화 첫 작업. 기능 개발·신규 렌더·데이터 삭제·서버 재시작·migration·커밋·Push 없음.

## 사전 확인

- 디스크 `C:` 여유 657 GB (필요량 약 2 GB). 실행 계정 `Pro`, `docker exec` 접근 정상(우회 없음).
- 운영 DB `127.0.0.1:5432/cutory`: revision `e3a1c9d27b45`, 9.8 MB, 프로젝트 14, 소스 11, 장면 후보 58, 편집 계획 6, 렌더 COMPLETED 3, VLM 화면 근거 8, 다른 active 쿼리 0. 8000의 처리·장면 분석·렌더 활성 작업 0건(14개 프로젝트).
- 저장 경로(코드 `backend/app/main.py`): 원본 `storage/originals/projects/<project>/sources/`, 렌더 `outputs/projects/projects/<project>/renders/<render>/{final.mp4, final.srt, final-subtitled.mp4}`. `uploads/`는 없음. 세 경로 모두 `.gitignore` 대상.

## 백업

- 위치: 저장소 밖 `C:\Users\Pro\Documents\Cutory-Backups\backup-20261104-165721\` (Git 추적 밖, 외부 업로드 없음, `.env`·비밀번호 미포함). 폴더 크기 1.9 GB. 복원 절차는 같은 폴더의 `RESTORE.md`.
- DB: 컨테이너 안 `pg_dump -Fc`(17.11) → `db/cutory-e3a1c9d27b45.dump` 113,444 B, SHA-256 `684d1171…0d01`(컨테이너 안·복사본 일치), `pg_restore -l` TABLE DATA 17. 컨테이너 임시 파일 삭제.
- 파일: `storage/`·`outputs/`의 37개 파일 2,031,083,308 B를 읽기 전용으로 해시한 뒤 `files/`에 복사하고 복사본 해시를 재계산 — 전부 일치, 복사 중 원본 변경 0. 종류별: 원본 11(2,018,930,028 B), 렌더 MP4 9, 하드 자막 MP4 8, SRT 9.
- DB 교차 확인(읽기 전용 세션): 소스 11/11 파일 존재·저장된 지문 일치. 렌더 기록 3건의 기본 MP4·SRT·하드 자막 모두 경로·크기·SHA-256 일치. WEB-08B 이전 렌더 파일(DB 기록 없음)도 매니페스트에 포함.

## 격리 복원 리허설

- 격리 PostgreSQL(55432)에 새 DB `cutory_restore_check_20261104` 생성 → `pg_restore --exit-on-error --no-owner` 성공, revision `e3a1c9d27b45`.
- 운영 DB(읽기 전용 세션)와 비교: 17개 테이블(alembic_version 포함) 490행, **모든 테이블의 전체 컬럼 md5 일치**, 제약조건 85/85, 인덱스 47/47.
- 사용자 데이터 사본이므로 검증 후 이 복원 DB와 컨테이너 임시 덤프를 삭제했다.

## 원본 변경 여부

없음. 백업 후 운영 DB revision·행 수 동일, 37개 파일의 SHA-256과 파일 목록 동일, 8000 PID 13384·5173 PID 41712 유지.

## 남은 작업·주의

- 렌더·분석 후에는 새 백업이 필요하다(이 백업은 2026-11-04 16:57 시점). 정기 백업·보관 개수는 정하지 않았다.
- 백업은 같은 디스크에 있다. 디스크 장애 대비 외부 매체 보관은 사용자 결정 사항이다.
- 격리 컨테이너(55432)에 과거 검증용 복원 DB 8개(`cutory_qa06_restore_*`, `cutory_qa07_*` 등)가 남아 있고 일부는 사용자 데이터 사본이다. 정리는 승인 후.
