# EIBE 통합 플랫폼

사내 SCM 대시보드와 Sales Hub 를 **하나의 프로젝트로 재구축**하는 중이다.
작업은 `eibe/` 폴더에서 하고, 완료 후 루트로 승격한다. 브랜치는
`feat/unified-platform`.

## 작업 시작 전에 읽을 것

| 문서 | 내용 |
|---|---|
| **`eibe/docs/STATE.md`** | 현재 진행 상황 · 로드맵 · 확정된 결정 · 미결 사항. **작업할 때마다 갱신한다** |
| `eibe/docs/patterns.md` | 성공 패턴 아카이브 (P-01~). 이 프로젝트에서 실제로 겪고 해결한 것만 |

`eibe/docs/STATE.md` 를 먼저 읽으면 다음에 할 일과 왜 그렇게 하기로 했는지가
모두 나온다. 아래는 그중 매 세션에 필요한 것만 추린 것이다.

## 헷갈리기 쉬운 것

- `sales code/` 는 **Salesforce 가 아니다.** 자체 제작한 사내 매출 대시보드다.
  사용자가 "세일즈 포스"라고 부른다
- 구 `.agents/AGENTS.md` 는 Claude Code 가 자동으로 읽지 않는 위치였다. 살릴
  내용은 `eibe/docs/STATE.md` §6 에 옮겨져 있다

## 절대 규칙

### 데이터
- 금액은 `app/models/types.py` 의 `Money`/`UnitPrice`/`Rate`/`Percent` **만** 쓴다.
  `Numeric(...)` 직접 사용 금지 — SQLite 는 float64 경유라 유효자릿수 15가 한계다
- 테이블명은 소문자 snake_case (Postgres 가 식별자를 소문자로 접는다)
- 날짜는 `Date`, ISO 주차는 물리 컬럼(`iso_year`/`iso_week`)
- 스키마 변경은 Alembic 으로만. `create_all()` 은 테스트 전용
- 원시 SQL 금지, SQLAlchemy 표현식만

### 보안
- **인증이 기본값이다.** 공개 엔드포인트는 별도 `public_router` 에 둔다.
  FastAPI 는 라우터·라우트 의존성을 **합치므로** `dependencies=[]` 로 해제되지 않는다
- 시크릿을 코드에 두지 않는다. `settings` 경유만

### 인코딩 (한국어 Windows)
- `alembic.ini` 와 `*.bat` 는 **ASCII 전용**. 로케일 인코딩(cp949)으로 읽히므로
  한글이 들어가면 명령 자체가 죽는다

### 설계
- 머신러닝 금지. 사칙연산 기반 통계 평탄화만 — 예측 근거가 항상 드러나야 한다
- 프론트엔드 프레임워크·번들러 금지. 네이티브 ES Module 로 빌드 없이 구동
- 동기화하지 않는다. 판매 원장 하나에서 파생시킨다

## 업무 규칙

- **재고일수 히트맵** — `<6주` risk-high 위험 · `6~9` risk-mid 주의 ·
  `9~13` risk-low 양호 · `>13` risk-safe 과잉 (13주 = 3개월이 적정)
- **발주** — 리드타임을 고려해 **6개월 뒤 도착분**을 주문한다
- **이관** — 용인 메인창고(HUB) → 각 풀필먼트 창고
- **유통기한** — FEFO(선입선출). `ELECTRONICS` 브랜드는 화면에서 **'보증기한'** 으로 치환
- **자산 평가** — 마스터 예상 단가가 아니라 인보이스 **실제 결제 원화 금액**을 역추적
- **주차 표기** — `Jun-W3` (영문 3글자, 한글 금지)
- **날짜 표기** — `2026년 6월 19일 (목)`

## UI 원칙

- 모던 B2B. 이모지 금지(SVG 아이콘만), 플랫 디자인(그라데이션·그림자 금지)
- 색상: 긍정 `#29AD3A` · 주의 `#e08a00` · 위험 `#e53535`
- 테이블: 텍스트 좌측 · 숫자 우측 · 상태 중앙. 긴 문자열에 `text-overflow: ellipsis`
- 클라이언트 계산은 **실시간**. "시뮬레이션 실행" 버튼을 두지 않는다
- 결측값은 `-` 나 `소진 불가` 로 대체해 화면이 깨지지 않게 한다

## 작업 방식

- **주장하기 전에 측정한다.** "타입을 바꿨다"고 쓰기 전에 실제로 넣어보고 확인한다
- **기능이 끝나면 실데이터로 전 구간을 한 번 돌린다.** 단위 테스트는 상상한
  입력만 검증한다 (이렇게 해서 잡은 버그가 `patterns.md` P-02, P-14)
- **새로 겪은 문제만** `patterns.md` 에 추가한다. 예방 차원의 일반론을 넣으면
  아카이브의 신뢰가 무너진다
- Phase 단위로 커밋하고, 메시지에 *무엇을* 뿐 아니라 *왜* 를 남긴다
- API 무응답 시 코드부터 파헤치지 말고 **좀비 uvicorn 프로세스**를 먼저 의심한다

## 자주 쓰는 명령

```bash
cd eibe
.venv/Scripts/python.exe -m pytest                    # 253개 통과해야 정상
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m scripts.seed_dev          # 개발 계정 + 샘플 데이터
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

개발 계정: `admin` / `operator` / `viewer`, 비밀번호 모두 `dev-password-1234`.
