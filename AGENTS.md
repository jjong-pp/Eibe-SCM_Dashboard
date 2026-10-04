# EIBE SCM Dashboard

사내 PC 한 대에서 단독 실행하는 SCM ERP. 발주·생산·입고 데이터를 한 화면으로 모으고, 출고 이력 기반 통계로 발주량을 제안한다.
기획 상세는 `docs/spec.md`, 과거 장애 기록은 `docs/history.md`. 필요할 때만 읽는다.

## 스택과 제약
- Python 3.12, FastAPI, SQLAlchemy 2, Pydantic 2, SQLite (`data/local_erp.db`, WAL)
- 프론트: 순수 HTML/CSS/JS. React·Vue 등 프레임워크 금지. 차트는 Chart.js 4 (CDN)
- 예측: 사칙연산 통계만. ML 라이브러리 금지
- 클라우드·외부 서비스 의존 추가 금지

## 구조
| 경로 | 내용 |
|---|---|
| `app/main.py` | 앱 생성, lifespan, 예외 처리기, 라우터 등록 |
| `app/routers/` | API (auth, users, master, pipeline, inventory, system, views) |
| `app/core/` | forecasting, excel_parser, auth, snapshot |
| `app/models.py`, `app/schemas.py`, `app/database.py` | ORM 모델, Pydantic 스키마, DB 연결 |
| `web/*.html` | 페이지 7개 (로직은 인라인 script) |
| `web/static/css/style.css`, `web/static/js/app.js` | 유일한 스타일시트, 공통 JS |
| `tests/` | pytest. 임시 DB + 고정 시드 |
| `scripts/` | verify.py(검증), squad.py(스쿼드 운영), sync_agents.py, hooks/ |
| `.agents/` | 역할(roles)·스킬(skills) 원본 |
| `.squad/` | 작업 기록: brief, backlog, contracts, reports, progress, lessons |
| `이전현황.md` | 기기 간 인계 기록 (현재 상태, 다음 할 일) |

## 명령어
- 서버: `start_server.bat` 또는 `venv\Scripts\python -m uvicorn app.main:app --port 8000`
- 개발 의존성: `venv\Scripts\python -m pip install -r requirements-dev.txt`
- 전체 검증: `python scripts/verify.py --tests` (정적 검사 + ruff + pytest)
- 시드: `venv\Scripts\python seed_data.py` (기존 데이터 삭제. `SCM_DB_PATH`로 대상 DB 지정)
- 스쿼드 현황: `python scripts/squad.py status`
- API 무응답이면 코드보다 먼저 uvicorn 프로세스를 종료하고 재시작한다 (dev-server 스킬)

## 기기 간 인계
여러 PC에서 같은 상황을 이어서 작업한다. 기준 파일은 루트 `이전현황.md`다. AI 도구의 메모리는 PC마다 따로라 공유되지 않는다.
- 사용자가 "이전현황 기록", "현황 정리", "인수인계"를 요청하면 **매번** `resume` 스킬 A 절차로 갱신하고 커밋한다
- 새 채팅이나 다른 PC에서 시작하면 `resume` 스킬 B 절차로 상태를 맞춘 뒤 "다음 채팅에서 할 일"부터 진행한다

## 수정 원칙
1. 함수·변수·CSS 클래스·DOM id·API 필드·DB 컬럼을 바꾸면 전체 참조를 찾아 함께 고친다 (impact-check 스킬)
2. `app.js`·`style.css`를 바꾸면 `web/*.html` 7개 전부 영향을 확인한다
3. API 응답을 화면에 바인딩할 때 null/undefined 가드 필수. 결측값은 `-` 등으로 표시
4. 클라이언트 계산·시뮬레이션은 버튼 없이 입력 즉시 반영한다
5. 테스트를 삭제하거나 약화(skip, assert 제거)하지 않는다
6. 지시 범위 밖 리팩토링·기능 추가 금지. 필요하면 보고만 한다
7. 운영 DB(`data/local_erp.db`)에 테스트 데이터를 쓰지 않는다
8. 커밋·push는 사용자 확인 후. 메시지 형식 `type: 요약` (feat, fix, refactor, docs, test, chore)

## 도메인 기준값
- 재고일수 히트맵 (13주 적정): 6주 미만 `risk-high` / 6~9주 `risk-mid` / 9~13주 `risk-low` / 13주 초과 `risk-safe`
- 발주는 리드타임을 고려해 6개월(24주) 뒤 도착분을 주문
- 재고 자산은 입고 실결제 원화(`InboundDB.payment_amount_krw`) 기준. `InvoiceDB`는 폐기됨
- 창고: hub(용인 메인), online, offline, buyout, coupang. 이관은 hub → 각 풀필먼트
- `brand_category`: FOOD는 유통기한, ELECTRONICS는 보증기한으로 화면 문구 치환
- 표기: 주차 `Jun-W3`, 날짜 `2026년 6월 19일 (목)`. 한글 주차 금지

## AI 스쿼드
메인 세션이 PM이다. 코드 변경 요청은 `squad-run` 스킬 절차를 따른다.

| 역할 | 담당 | 비고 |
|---|---|---|
| PM (메인 세션) | 요구 기록, 크기 판정(S/M/L), 계약서, 배분, 최종 보고 | S 작업만 직접 수정 |
| front | `web/` | |
| back | `app/routers/`, `app/core/`(snapshot 제외), `app/schemas.py`, `app/main.py`, `tests/` | |
| data | `app/models.py`, `app/database.py`, `app/core/snapshot.py`, `seed_data.py`, 마이그레이션 | |
| reviewer | 앱 실행·루브릭 채점 | 코드 수정 금지. 빌더와 다른 모델 계열 |
| police | 계약·룰 준수 감사 | 코드 수정 금지. 결과는 사용자에게 그대로 |
| explorer | 참조·영향 범위 조사 | 읽기 전용 |

- 작업 기록: `.squad/backlog.json` (작업 목록), `.squad/contracts/T-###.md` (계약서). `passes`는 `squad.py close`로만 바꾼다
- 역할·스킬 원본은 `.agents/`. 수정 후 `python scripts/sync_agents.py`로 `.claude/`, `.codex/agents/`를 다시 생성한다. 생성물은 직접 고치지 않는다
- 훅이 자동으로: 위험 명령 차단, 파일 수정 직후 정적 검사, 턴 종료 시 전체 검증 (실패하면 계속 작업, 연속 3회 실패 시 사용자 보고)
- 기존 결함은 `.squad/verify-baseline.txt`에 있다. 고치면 지우고, 새로 추가하려면 사용자 승인이 필요하다
- Codex에서 역할 에이전트는 이름으로 명시해 띄운다 (예: "front 에이전트로 T-004 수행")
