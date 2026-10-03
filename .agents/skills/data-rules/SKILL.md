---
name: data-rules
description: app/models.py, app/database.py, app/core/snapshot.py, seed_data.py, 마이그레이션, 서버 기동 스크립트를 수정할 때 따르는 DB·서버 운영 규칙.
---

# data-rules

## 현재 상태
- SQLite 단일 파일 `data/local_erp.db`, WAL 모드, `foreign_keys=ON` (app/database.py)
- 스키마 생성은 `init_db()`의 `create_all`뿐이다. 마이그레이션 도구는 아직 없다
- `SCM_DB_PATH`, `SCM_BACKUP_DIR` 환경변수로 DB·백업 경로를 바꾼다 (테스트·QA용)
- 스냅샷: app/core/snapshot.py + APScheduler. 종료 시 `scheduler.shutdown(wait=False)`를 유지한다 (서버 무응답 방지)

## 규칙
- 컬럼 삭제·이름 변경·타입 변경은 마이그레이션, 데이터 이전, 롤백 방법을 함께 낸다. 계약서에 사용자 승인이 있어야 한다
- 마이그레이션 도구 도입 전에는 기본값이 있는 컬럼 추가만 한다
- 운영 DB에 직접 쓰지 않는다. 검증은 임시 DB로 한다
- relationship을 중복 선언하지 않는다
- 정규화는 3NF 기준. 의도적으로 중복 저장하는 컬럼은 이유를 주석으로 남긴다
- 인덱스를 추가하면 대상 쿼리와 `EXPLAIN QUERY PLAN` 결과를 증거로 낸다
- seed_data.py는 모든 테이블을 채워 화면 전체가 보이게 유지한다. 모델을 바꾸면 시드도 같이 바꾼다

## 서버 운영
- 기동·재시작·포트 점유 해결은 dev-server 스킬 참고
- 백업은 `data/backups/` (git 제외). 복원은 `/api/snapshot/restore/{id}`
