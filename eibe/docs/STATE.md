# 개발 상태 — 인수인계 문서

> **갱신 시점** 2026-08-14 · **브랜치** `feat/unified-platform`
>
> 다른 PC 에서 작업을 이어받을 때 이 문서만 읽으면 방향·속도·판단 기준이
> 그대로 유지되도록 쓴 것이다. **작업을 진행할 때마다 갱신한다.**

---

## 1. 지금 어디까지 왔나

```
c98646f  feat(eibe): Phase 3 (part 2) — analytics and excel services
fab7ec1  fix(eibe): make requirements.txt installable on Korean Windows
d0f5480  refactor(eibe): resolve the three open decisions
159071f  docs: record project state for handoff across machines
2ed69af  feat(eibe): Phase 3 (part 1) — forecasting and derived aggregates
297d44a  feat(eibe): Phase 2 — unified domain model
2e4a82e  feat(eibe): Phase 1 — application skeleton
2c05615  chore: preserve Sales Hub draft before unified rebuild
57c80d9  (master 시작점 — 구 SCM 코드)
```

> ⚠️ **이 브랜치는 아직 원격에 push 되지 않았다.** 다른 PC 에서 이어받으려면
> 먼저 올려야 한다 — §7.1 참조.

| 항목 | 수치 |
|---|---|
| Python 코드 | 약 5,200줄 (+ 테스트 2,900줄) |
| 테스트 | 253개 (전부 통과) |
| 마이그레이션 | 2건 |
| 도메인 테이블 | 14개 |

`.agents/AGENTS.md` 는 삭제 확정됐다. 살릴 내용은 루트 `CLAUDE.md` 와 이 문서 §6
으로 옮겨졌고, 원본이 필요하면 `git show 57c80d9:.agents/AGENTS.md` 로 꺼낸다.

---

## 2. 무엇을 만들고 있나

사내 두 앱을 **하나의 프로젝트로 전면 재구축**한다.

| 원본 | 정체 |
|---|---|
| `app/` + `web/` | 구 SCM Dashboard — FastAPI + SQLite, 재고·발주 예측 |
| `sales code/` | 구 Sales Hub — 순수 JS 매출 대시보드 8,092줄 |

> **주의:** `sales code/` 는 사용자가 "세일즈 포스"라 부르지만 **Salesforce CRM 이
> 아니다.** 자체 제작한 사내 매출 대시보드다. 원래 Firestore 를 쓰다 REST 로
> 옮긴 흔적이 남아 있다 (`FirestoreStore` 별칭, `WRITE_BATCH_SIZE` 설정).

**진행 방식 (사용자 지정):**
1. 루트에 `eibe/` 폴더를 만들어 통합 코드를 **새로 작성** ← 현재 여기
2. 기존 `app/` · `web/` · `sales code/` 폐기
3. `eibe/` 내용을 루트로 꺼내 배포용 저장소 구조로 정리

---

## 3. 로드맵

| Phase | 내용 | 상태 |
|---|---|---|
| 0 | 안전망 — `sales code/` 커밋 | ✅ |
| 1 | 골격 — config · DB · Alembic · 인증 | ✅ |
| 2 | 통합 도메인 모델 (14개 테이블) | ✅ |
| 3a | `forecasting` · `derive` 서비스 | ✅ |
| 3b | `analytics` 포팅 · `excel` 서비스 | ✅ |
| **4** | **API 라우터 (SCM + Sales Hub 계약)** | **← 다음** |
| 5 | 프론트엔드 통합 | ⬜ |
| 6 | 시딩 · 테스트 마무리 | ⬜ |
| 7 | 루트 승격 · 구 코드 폐기 · 문서 개정 | ⬜ |

### Phase 3b 결과 (완료)

- **`services/analytics.py`** — 구 `analytics.js` 1,074줄 포팅. KPI · 채널 믹스 ·
  포트폴리오 · 행사 ROI · 알림 · 추이. 임계값은 구
  `SheetSchema.ANALYTICS_THRESHOLDS` 를 그대로 옮겼다
  (`ALERT_PRODUCT_UP=50`, `ALERT_PRODUCT_DOWN=-25`, `ALERT_CHANNEL_DOWN=-20`, `ALERT_MAX=5`).
  옮기면서 바꾼 판단은 D14~D17 참조.
- **`services/excel.py`** — 7종 양식 생성 · 파싱 · 검증 · 매핑 · 청크 적재.
  판매 업로드는 끝나면 해당 주차만 재집계한다.

**포팅하지 않은 것** — 구 `analytics.js` 의 `detailCatalog` / `buildWhy`.
채널·제품을 눌렀을 때 나오는 드릴다운과 "왜 변했나" 서술이다. 계산이 아니라
문장 조립("전주 대비 ▲12.3%", "행사 리프트 가능")이라 화면 형태가 정해지는
Phase 5 에서 만드는 편이 맞다. 재료(주차별 채널·라인업 집계, 겹치는 행사)는
이미 `analytics.py` 안에 있다.

### Phase 4 에서 구현해야 할 API 계약

구 `sales code/data/apiStore.js` 가 **이미 이 엔드포인트들을 호출하도록 작성되어
있다.** 프론트를 새로 쓰더라도 계약을 알고 있어야 한다.

```
GET/POST  /brands
GET/PUT   /brands/{id}/sheets/{sheetId}
PATCH     /brands/{id}/sheets/{sheetId}/rows
GET       /brands/{id}/bundle
GET/POST  /audit
POST      /auth/login    GET /auth/me
```

---

## 4. 확정된 결정 — 다시 논의하지 않는다

각 항목은 사용자와 합의된 것이다. 뒤집으려면 사용자 확인이 필요하다.

| # | 결정 | 근거 |
|---|---|---|
| D1 | **동기화 대신 파생** | 같은 DB 로 합치면 동기화 대상이 없다. 판매 원장 하나에서 SCM 집계를 파생시킨다 |
| D2 | **SQLite → Firebase Data Connect** (관리형 PostgreSQL) | 전환 실체는 SQLite→Postgres 이고 SQLAlchemy 가 흡수한다 |
| D3 | **FastAPI 를 앞에 유지** | 브라우저가 Firebase 에 직접 붙지 않는다. Python 서비스 계층을 지키고 Security Rules 로 SCM 권한을 표현하는 지옥을 피한다 |
| D4 | **스케줄러 제거** | 인프로세스 스케줄러는 인스턴스가 늘면 중복 실행되고 서버리스에서 안 돈다 |
| D5 | **백업 기능 통합 범위에서 제외** | Cloud SQL 자동 백업/PITR 로 대체 |
| D6 | **정규화 테이블** | 시트 배열 그대로 저장하지 않는다 |
| D7 | **프레임워크·번들러 없음** | 네이티브 ES Module 로 "빌드 없이 즉시 구동" 유지 |
| D8 | **ML 금지** | 사칙연산 기반 통계 평탄화만. 예측 근거가 항상 드러나야 한다 |
| D9 | **httpOnly 쿠키 + CSRF 이중제출** | localStorage 토큰의 XSS 노출 제거 |
| D10 | **폴더명 `eibe/`** | `platform/` 은 Python stdlib 모듈명이라 네임스페이스 패키지로 stdlib 을 가릴 수 있다 |
| D11 | **발주 테이블 하나로 통합** | 구 `ORDER_DB`(발주)와 `MONTHLY_ORDER_PLAN`(계획)이 같은 사실을 두 곳에 저장했다. 발주는 월 1회이므로 확정된 계획이 곧 주문이다 → `MonthlyOrderPlan.status=CONFIRMED` + `purchase_code` |
| D12 | **`.agents/AGENTS.md` 삭제** | Claude Code 가 읽지 않는 경로였다. 살릴 규칙은 루트 `CLAUDE.md` 와 §6 으로 이관. 원본은 `57c80d9` 에 |
| D13 | **Data Connect vs 일반 Postgres 는 배포 시점에 결정** | 둘 다 PostgreSQL 이라 설계·코드가 동일하다. 지금 정할 이유가 없다 |
| D14 | **주간 비교는 같은 경과일수끼리** | 구 버전은 이번 주만 기준일에서 자르고 직전 주는 일요일까지 통째로 썼다. 수요일에 열면 3일 대 7일이라 WoW 가 늘 폭락으로 보인다. 월 비교는 구 버전도 `sameDayPrevMonth` 로 맞춰져 있었으므로 주 비교를 거기에 맞춘 것이다 |
| D15 | **서비스 출력에 HTML 을 넣지 않는다** | 구 알림 문구에는 `<strong>` 이 박혀 있었다. 표현을 서비스가 정하면 재사용이 막히고, 그 문자열을 innerHTML 에 꽂으면 업로드된 제품명이 스크립트가 된다 |
| D16 | **'기준선 없음'은 `None`, 큰 수로 채우지 않는다** | 구 버전은 리프트를 `99999`, 시작 전 행사를 `-100%` 로 내보냈다. 화면이 `-` 로 그릴 수 있게 없음을 없음으로 돌려준다 |
| D17 | **pandas 제거, openpyxl 만 쓴다** | 시트를 행 단위로 읽는 데 DataFrame 이 필요 없다. pandas 는 빈 칸을 `NaN`(float) 으로 만들어 구 파서가 셀마다 `pd.notna()` 와 `str()` 을 두르게 했고, 그 과정에서 날짜·금액이 문자열로 뭉개졌다 |

### D11 보충 — 발주 추적이 끊기지 않는 이유

```
MonthlyOrderPlan(status=CONFIRMED, purchase_code="PC-...")
        │  같은 발주번호
        ▼
Inbound(purchase_code="PC-...", status=입고완료)
```

실제 발주 수량은 `MonthlyOrderPlan.order_qty` 프로퍼티(= `user_modified_qty`)로
읽는다. 실무자가 조정한 값이 시스템 제안보다 우선한다.

한 발주월에 같은 품목을 여러 건으로 쪼개 주문하는 운영이 생기면 그때 별도
테이블을 되살린다. **쓰이지 않는 테이블을 미리 들고 가지 않는다** — 반쯤
구현된 채로 남아 어느 쪽이 진실인지 흐려진다.

### Firestore 를 전제로 했다가 **철회한** 것

한때 Firestore(NoSQL) 전환을 가정했으나 Data Connect(=PostgreSQL) 로 확정되며
아래 제약은 불필요해졌다. **다시 도입하지 말 것.**

- ~~Port-Adapter 추상화 계층~~ → SQLAlchemy 가 이미 방언을 추상화
- ~~금액을 정수 최소단위로~~ → `Numeric` 유지 (단, §5 정밀도 한계는 지킴)
- ~~ULID 문자열 PK~~ → `int` autoincrement 로 충분
- ~~읽기용 역정규화 필드 강제~~ → JOIN 이 되므로 성능 목적일 때만

---

## 5. 반드시 지킬 규약

### 5.1 PostgreSQL 이식성

전환 비용을 0으로 유지하는 규칙. **하나만 어겨도 나중에 전수 수정**이다.

1. **테이블명은 소문자 snake_case** — Postgres 는 따옴표 없는 식별자를 소문자로
   접는다. 대문자는 영구히 따옴표를 달아야 한다
2. **타입을 정확히** — SQLite 는 동적 타입이라 통과하지만 Postgres 는 거부한다
3. **원시 SQL 금지, SQLAlchemy 표현식만** — 날짜 함수·문자열 연결이 방언마다 다르다
4. **정렬 없는 페이지네이션 금지** — SQLite 는 우연히 일관되지만 Postgres 는 아니다
5. **연결 설정은 `config.py` 분기** — 전환 시 `.env` 한 줄만 바뀌게
6. **모든 스키마 변경은 Alembic** — `create_all()` 은 테스트에서만

### 5.2 금액 정밀도

`app/models/types.py` 의 `Money` / `UnitPrice` / `Rate` / `Percent` **만** 쓴다.
`Numeric(...)` 을 직접 쓰지 않는다.

SQLite 에는 네이티브 DECIMAL 이 없어 float64 를 경유하고, 유효자릿수가 15를 넘으면
조용히 반올림된다. 실측: `Numeric(18,2)` 에 `999999999999999.99` → `1000000000000000.00`.

### 5.3 인코딩 (한국어 Windows)

- **`alembic.ini` · `*.bat` 는 ASCII 전용** — 로케일 인코딩(cp949)으로 읽히므로
  한글이 들어가면 명령 자체가 죽는다
- 한글 설명은 `.py` 에 둔다 (UTF-8 로 읽도록 지정된 파일)
- stdout/stderr UTF-8 고정은 `app/__init__.py` 에서 처리됨 — 건드리지 말 것

### 5.4 보안

- **인증이 기본값** — 공개 엔드포인트는 별도 라우터(`public_router`)에 둔다.
  FastAPI 는 라우터·라우트 의존성을 **합치므로** `dependencies=[]` 로 해제되지 않는다
- 시크릿을 코드에 두지 않는다. `settings` 경유만
- 개발용 시드 스크립트는 production 에서 실행을 거부해야 한다

### 5.5 작업 방식

- **주장하기 전에 측정한다.** "타입을 바꿨다"고 쓰기 전에 실제로 넣어보고 확인한다.
  P-02(금액 정밀도)와 P-14(파이프라인 결손)는 둘 다 이렇게 발견됐다
- **기능이 끝나면 실데이터로 전 구간을 한 번 돌린다.** 단위 테스트는 내가 상상한
  입력만 검증한다
- **새로 겪은 문제는 `docs/patterns.md` 에 추가한다.** 겪지 않은 일반론은 넣지 않는다
- Phase 단위로 커밋한다. 커밋 메시지에 *무엇을* 뿐 아니라 *왜* 를 남긴다

---

## 6. 구 AGENTS.md 에서 살릴 업무 규칙

원본은 커밋 `57c80d9` 의 `.agents/AGENTS.md` (227줄). 아키텍처 설명은 이번
개편으로 무효가 됐고, 아래만 유효하다. 요약본은 이미 루트 `CLAUDE.md` 에 있으며,
여기에는 근거와 세부를 남긴다.

### 6.1 재고일수 히트맵 (3개월 = 13주 적정)

| 구간 | 색 | 클래스 | 의미 |
|---|---|---|---|
| < 6주 | 빨강 | `risk-high` | 위험 — 품절 임박 |
| 6~9주 | 노랑 | `risk-mid` | 주의 — 발주 검토 |
| 9~13주 | 초록 | `risk-low` | 양호 — 적정 |
| > 13주 | 파랑 | `risk-safe` | 과잉 — 이관/할인 검토 |

→ 이미 `app/services/forecasting.py` 의 `StockRisk` / `RISK_THRESHOLDS_WEEKS` 로 구현됨.

### 6.2 업무 규칙

- **발주:** 리드타임을 고려해 **6개월 뒤 도착분**을 주문한다. UI 에 명시할 것
- **이관:** 용인 메인창고(HUB) → 각 풀필먼트 창고. 한 창고에 여러 SKU 이동 가능
- **유통기한:** FEFO(선입선출)
- **자산 평가:** 마스터 예상 단가가 아니라 **인보이스 실제 결제 원화 금액**을 역추적
- **브랜드:** `ELECTRONICS` 는 화면에서 '유통기한' → **'보증기한'** 으로 치환
- **창고 종류:** hub(용인 메인) · online · offline · buyout

### 6.3 표기 규칙

- **주차:** 영문 월약어 3글자 — `Jun-W3`. **한글 주차 표기 금지**
- **날짜:** `2026년 6월 19일 (목)`
- **테이블 정렬:** 텍스트 좌측 · 숫자 우측(`text-right`) · 상태 중앙
- **결측값:** 화면이 깨지지 않도록 `-` 또는 `소진 불가` 등 대체 텍스트

### 6.4 UI 원칙

- 모던 B2B — 장식적 애니메이션 지양
- **이모지 금지, SVG 아이콘만**
- **플랫 디자인** — 그라데이션·그림자 금지
- 색상: 긍정 `#29AD3A` · 주의 `#e08a00` · 위험 `#e53535`
- **클라이언트 계산은 실시간(Reactive)** — "시뮬레이션 실행" 버튼을 두지 않는다
- 다크모드 유지 (CSS 변수 기반)

### 6.5 과거 사고 이력 중 아직 유효한 것

- **API 무응답 시** 코드부터 파헤치지 말고 **좀비 uvicorn 프로세스**를 먼저 의심한다
- 테이블에 긴 문자열이 들어가면 레이아웃이 깨진다 — `max-width` · `overflow: hidden`
  · `text-overflow: ellipsis` 를 기본으로 건다
- 클라이언트 단순 연산에 실행 버튼을 두지 않는다 (6.4 와 동일)

---

## 7. 처음부터 띄우기

> 아래 절차는 **빈 클론에서 한 줄씩 실제로 실행해 검증했다** (2026-08-14).
> 검증 과정에서 `requirements.txt` 인코딩 문제가 드러나 고쳤다 — 자세한 내용은
> `docs/patterns.md` P-16. 절차를 고치면 다시 빈 클론에서 확인할 것.

```bash
git clone <repo> && cd <repo>/eibe
git checkout feat/unified-platform

python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt

cp .env.example .env
# EIBE_SECRET_KEY 를 채운다:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
# 비워두면 임시 키가 생성되어 재시작마다 세션이 만료된다 (로컬은 무방)

.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m scripts.seed_dev
.venv/Scripts/python.exe -m pytest              # 253개 통과해야 정상
```

서버 실행 — `start_server.bat` 더블클릭, 또는:

```bash
.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**개발용 계정** (`seed_dev` 가 생성, production 에서는 실행 거부):

| 계정 | 비밀번호 | 권한 |
|---|---|---|
| `admin` | `dev-password-1234` | ADMIN |
| `operator` | `dev-password-1234` | OPERATOR |
| `viewer` | `dev-password-1234` | VIEWER |

`.env` 와 `.venv/`, `data/*.db` 는 gitignore 대상이므로 PC 마다 다시 만든다.

### 7.1 다음 PC 로 옮기기 — 먼저 push 해야 한다

**작성 시점에 `feat/unified-platform` 은 원격에 올라가 있지 않다.** 클론으로는
받을 수 없으므로, 다른 PC 로 넘기려면 먼저 올려야 한다.

```bash
git push -u origin feat/unified-platform
```

원격 저장소는 `origin` (GitHub) 하나가 설정되어 있다. push 후 다음 PC 에서:

```bash
git clone <repo-url> && cd <repo>
git checkout feat/unified-platform
```

이후는 위 §7 절차 그대로다.

**gitignore 때문에 따라가지 않는 것** — 각 PC 에서 다시 만든다:

| 항목 | 만드는 법 |
|---|---|
| `.venv/` | `python -m venv .venv` + `pip install -r requirements.txt` |
| `eibe/.env` | `cp .env.example .env` (시크릿은 비워도 로컬은 동작) |
| `eibe/data/eibe.db` | `alembic upgrade head` + `scripts.seed_dev` |

**저장소에 없어도 되는 것**: 로컬 DB 는 시드로 재생성되므로 옮길 필요가 없다.
난수 시드를 고정해 두었기 때문에 어느 PC 에서든 같은 샘플 데이터가 나온다.

---

## 8. 미결 사항

없음. 이전에 열려 있던 3건은 D11 · D12 · D13 으로 정리됐다.

새로 판단이 필요한 것이 생기면 여기에 적고, 결정되면 §4 로 옮긴다.

---

## 9. 파일 지도

```
eibe/
├── docs/
│   ├── STATE.md        ← 이 문서. 작업할 때마다 갱신한다
│   └── patterns.md     ← 성공 패턴 아카이브 (P-01~P-15)
├── app/
│   ├── config.py       설정 단일 출처 (.env)
│   ├── database.py     방언 격리 — 여기만 고치면 Postgres 전환
│   ├── core/
│   │   ├── dates.py    ISO 주차 (연말 경계 주의)
│   │   ├── deps.py     인증·권한 가드
│   │   ├── middleware.py  요청 ID · CSRF
│   │   └── security.py PyJWT · bcrypt · CSRF 토큰
│   ├── models/
│   │   ├── types.py    ★ 금액 타입 — 반드시 여기 것만 쓴다
│   │   ├── enums.py    CHECK 제약이 여기서 생성된다
│   │   ├── master.py   brand · product · product_alias · warehouse · channel
│   │   ├── scm.py      inbound · inventory_snapshot · monthly_order_plan
│   │   ├── sales.py    sales_order · promotion
│   │   └── metrics.py  weekly_metric (파생)
│   ├── services/
│   │   ├── forecasting.py  순수 함수. DB 를 모른다
│   │   ├── derive.py       판매 원장 → 주차 집계 (멱등)
│   │   ├── analytics.py    매출 대시보드 지표 (구 analytics.js)
│   │   └── excel.py        양식 생성 · 업로드 파싱 · 적재
│   ├── routers/        auth · system (Phase 4 에서 확장)
│   └── schemas/
├── alembic/versions/   마이그레이션 2건
├── scripts/
│   ├── create_admin.py 운영용 계정 생성
│   └── seed_dev.py     개발용 시드 (production 거부, 멱등)
└── tests/              253개
```

### 접합점 — 이 두 개가 SCM 과 판매를 잇는 전부다

```
ProductAlias.source_name  →  Product      (구 lineup 시트)
Channel.warehouse_id      →  Warehouse    (구 channelGroup 시트)
```
