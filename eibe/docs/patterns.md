# 성공 패턴 아카이브

이 프로젝트에서 **실제로 겪고 측정해서 해결한 것**만 기록한다. 일반론이나
"좋다더라" 수준의 조언은 넣지 않는다. 각 항목은 다음 형식을 지킨다:

- **증상** — 어떻게 드러났는가 (재현 가능한 형태로)
- **원인** — 왜 그런가
- **해결** — 무엇을 했는가 (복사해서 쓸 수 있는 코드)
- **적용 범위** — 어디까지 유효한가

각 패턴에는 안정적인 ID(`P-nn`)가 있다. 나중에 이 문서를 API 로 제공하게
되면 ID 로 개별 조회할 수 있도록 붙여둔 것이다.

> 갱신 규칙: 새로 겪은 문제만 추가한다. 겪지 않은 문제를 예방 차원에서
> 적는 순간 이 문서는 신뢰를 잃는다.

---

## 목차

| ID | 제목 | 영역 |
|----|------|------|
| [P-01](#p-01) | FastAPI 라우터 의존성은 해제되지 않는다 | 보안 |
| [P-02](#p-02) | SQLite 금액 정밀도는 유효자릿수 15가 한계 | 데이터 |
| [P-03](#p-03) | 서드파티가 읽는 설정 파일은 ASCII 로 | 인코딩 |
| [P-04](#p-04) | Windows 콘솔 UTF-8 은 패키지 진입점에서 고정 | 인코딩 |
| [P-05](#p-05) | Alembic 제약조건 이름 규칙은 선택이 아니다 | 마이그레이션 |
| [P-06](#p-06) | 테이블명은 소문자 snake_case | 이식성 |
| [P-07](#p-07) | 제약 위반 테스트 뒤에는 롤백이 먼저 | 테스트 |
| [P-08](#p-08) | 시드 스크립트는 존재 확인으로 멱등하게 | 개발환경 |
| [P-09](#p-09) | CHECK 제약은 enum 에서 생성한다 | 데이터 |
| [P-10](#p-10) | 날짜는 Date, 주차는 물리 컬럼 | 데이터 |
| [P-11](#p-11) | 동기화 대신 단일 원장에서 파생 | 아키텍처 |
| [P-12](#p-12) | 서버 없이 ASGI 앱 직접 호출 | 테스트 |
| [P-13](#p-13) | 로그인 실패 응답 시간을 맞춘다 | 보안 |
| [P-14](#p-14) | 파이프라인은 실데이터로 한 번 끝까지 돌린다 | 테스트 |
| [P-15](#p-15) | 벌크 삭제는 세션 아이덴티티 맵을 정리한다 | SQLAlchemy |
| [P-16](#p-16) | 인수인계 문서는 빈 클론에서 실행해 검증한다 | 문서 |
| [P-17](#p-17) | 시드는 기능의 정상 경로를 지나가야 한다 | 개발환경 |

---

<a id="p-01"></a>
## P-01. FastAPI 라우터 의존성은 해제되지 않는다

**영역** 보안 · FastAPI

### 증상
공개 엔드포인트를 만들려고 라우트에 `dependencies=[]` 를 줬는데 계속 401 이 났다.

### 원인
FastAPI 는 라우터 레벨 의존성과 라우트 레벨 의존성을 **합친다**. 라우트에서
빈 리스트를 줘도 라우터 기본값이 사라지지 않는다. 반대 방향으로 착각하면
더 위험하다 — "라우터에 걸어뒀으니 안전하다"고 믿는데 실제로는 안 걸린 경우.

### 해결
공개용과 보호용 라우터를 **물리적으로 분리**한다.

```python
# 보호 — 소속된 모든 라우트에 자동 적용된다
router = APIRouter(prefix="/api/system", dependencies=[Depends(require_admin)])

# 공개 — 가드가 필요 없는 것만 담는다
public_router = APIRouter(prefix="/api/system")

@public_router.get("/health")   # 인증 없음
def health(): ...

@router.get("/diagnostics")     # 관리자 전용
def diagnostics(): ...
```

`main.py` 에서 둘 다 등록한다. 이렇게 하면 **가드를 붙이는 걸 잊어도 뚫리지
않는다** — 기본값이 "보호"이기 때문이다.

### 적용 범위
FastAPI 전 버전. 구 SCM 은 조회성 GET 에 가드를 하나씩 붙이는 방식이었고,
그 결과 `GET /api/users` 가 무인증으로 전체 계정을 노출하고 있었다.

---

<a id="p-02"></a>
## P-02. SQLite 금액 정밀도는 유효자릿수 15가 한계

**영역** 데이터 · SQLAlchemy

### 증상
`Numeric(18, 2)` 컬럼에 저장한 금액이 조용히 달라졌다.

```
입력  999999999999999.99
저장  1000000000000000.00
```

### 원인
SQLite 에는 네이티브 DECIMAL 이 없다. SQLAlchemy 가 float 를 경유해 저장하는데,
float64 는 2^53(≈9.007e15)까지의 정수만 정확히 표현한다. 정수부와 소수부를
합친 유효자릿수가 15를 넘으면 반올림된다.

**선언한 정밀도를 DB 가 지켜준다고 가정하면 안 된다.** 실제로 넣어보고 확인해야 한다.

### 해결
공용 타입 모듈에서 한계 안으로 고정한다. 매직 넘버를 컬럼마다 반복하지 않고
근거를 한 곳에 적는다.

```python
# app/models/types.py
_SAFE_SIGNIFICANT_DIGITS = 15   # float64 가 정확히 담는 한계

Money = Numeric(_SAFE_SIGNIFICANT_DIGITS, 2)      # 최대 9,999,999,999,999.99
UnitPrice = Numeric(_SAFE_SIGNIFICANT_DIGITS - 1, 4)
Rate = Numeric(12, 4)
Percent = Numeric(6, 3)
```

테스트로 한계값을 고정해둔다.

```python
def test_declared_precision_fits_float64():
    assert Money.precision <= 15

def test_largest_supported_amount_round_trips(db):
    limit = Decimal("9999999999999.99")
    ...
    assert stored == limit
```

### 적용 범위
SQLite. PostgreSQL 은 임의 정밀도라 이 제약이 없지만, 같은 코드가 양쪽에서
동일하게 동작해야 하므로 낮은 쪽에 맞춘다. **Float 로 돈을 다루지 않는다**는
원칙은 방언과 무관하게 유효하다.

---

<a id="p-03"></a>
## P-03. 서드파티가 읽는 설정 파일은 ASCII 로

**영역** 인코딩 · Windows

### 증상
`alembic.ini` 에 한글 주석을 달았더니 모든 alembic 명령이 죽었다.

```
UnicodeDecodeError: 'cp949' codec can't decode byte 0xec in position 10
```

### 원인
Alembic 은 `configparser` 로 ini 를 읽으면서 `encoding="locale"` 을 쓴다.
한국어 Windows 의 로케일 인코딩은 cp949 라, UTF-8 로 저장된 한글이 깨진다.
`.bat` 파일도 같은 문제를 겪는다 — cmd.exe 가 콘솔 코드페이지로 읽는다.

### 해결
**내가 인코딩을 통제할 수 없는 파일은 ASCII 로 유지**하고, 그 이유를 파일 안에 적는다.

```ini
# NOTE: Keep this file ASCII-only. Alembic reads it with the *locale* encoding
# (cp949 on Korean Windows), so non-ASCII comments break `alembic` commands.
# Korean documentation belongs in alembic/env.py, which is read as UTF-8.
```

한글 설명은 내가 인코딩을 지정해 읽는 파일(`.py`)에 둔다.

### 적용 범위
`.ini`, `.cfg`, `.bat`, `.cmd`, **`requirements.txt`**.
로케일이 UTF-8 인 환경에서는 문제가 없지만, 저장소는 어느 PC 에서든 동작해야 한다.

### 후일담 — 이 규칙을 스스로 어겼다

이 패턴을 적어두고도 `requirements.txt` 에 한글 주석과 `—`(em dash)를 넣었다.
신규 클론에서 설치가 첫 줄부터 죽었다.

```
UnicodeDecodeError: 'cp949' codec can't decode byte 0xe2 in position 24
```

그 뒤 `python -m alembic` 이 "No module named alembic.__main__" 로 실패했는데,
이건 별개 문제가 아니라 **설치가 안 됐기 때문**이었다. 원인 하나가 서로 무관해
보이는 증상 두 개로 나타난 것이다.

**판단 기준을 넓혀야 한다:** "내가 인코딩을 지정해 읽는 파일"이 아니라
**"외부 도구가 읽는 모든 텍스트 파일"** 이 대상이다. pip · cmd · configparser 는
전부 로케일 인코딩을 쓴다.

발견 경위는 [P-16](#p-16) 참조.

---

<a id="p-04"></a>
## P-04. Windows 콘솔 UTF-8 은 패키지 진입점에서 고정

**영역** 인코딩 · Windows

### 증상
한글 로그가 깨져서 나왔다. `configure_logging()` 안에서 stdout 을 재설정했는데도
**설정 로딩 중에 나오는 경고**는 여전히 깨졌다.

### 원인
경고가 `configure_logging()` 호출 **이전**에, 설정 객체를 만드는 시점에 발생했다.
로깅 설정 함수에서 인코딩을 고치면 이미 늦다.

### 해결
패키지 `__init__.py` 에서 처리한다. 어떤 하위 모듈보다 먼저 실행된다.

```python
# app/__init__.py
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
```

`errors="replace"` 를 넣어 인코딩 불가 문자가 예외를 던지지 않게 한다 —
로그 한 줄 때문에 프로세스가 죽으면 안 된다.

### 적용 범위
Python 3.7+. `PYTHONUTF8=1` 환경변수로도 해결되지만, 실행 환경에 의존하지
않으려면 코드에서 잡는 편이 확실하다.

---

<a id="p-05"></a>
## P-05. Alembic 제약조건 이름 규칙은 선택이 아니다

**영역** 마이그레이션

### 원인
이름 없는 제약조건은 Alembic 이 `downgrade()` 에서 지목할 수 없고, SQLite 의
batch ALTER(임시 테이블 우회)도 실패한다. DB 가 자동 생성한 이름은 방언마다
달라서 마이그레이션이 이식되지 않는다.

### 해결
`MetaData` 에 이름 규칙을 걸어두면 모든 제약에 자동으로 이름이 붙는다.

```python
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

`env.py` 에서 SQLite 일 때 batch 모드를 켠다.

```python
"render_as_batch": settings.is_sqlite,
"compare_type": True,          # Text → Date 같은 타입 변경을 놓치지 않는다
```

테스트로 강제한다.

```python
def test_all_constraints_are_named():
    unnamed = [
        f"{t.name}.{type(c).__name__}"
        for t in Base.metadata.sorted_tables
        for c in t.constraints
        if c.name is None
    ]
    assert unnamed == []
```

### 검증 방법
`upgrade → downgrade base → upgrade` 왕복이 깨끗이 도는지 확인한다.
마이그레이션을 되돌릴 수 없다는 건 배포 후에야 알게 되는 종류의 문제다.

---

<a id="p-06"></a>
## P-06. 테이블명은 소문자 snake_case

**영역** 이식성 · PostgreSQL

### 원인
PostgreSQL 은 따옴표 없는 식별자를 **소문자로 접는다**. `USER_ACCOUNT` 같은
대문자 이름은 SQLAlchemy 가 따옴표를 붙여 생성하므로 그대로 유지되지만,
그 뒤로 psql·덤프·외부 툴에서 **영구히 따옴표를 달아야** 한다.

### 해결
처음부터 소문자로 쓴다. 접미사 `_DB` 같은 장식도 뺀다 (`PRODUCT_DB` → `product`).

```python
def test_all_tables_are_lowercase():
    offenders = [
        t.name for t in Base.metadata.sorted_tables if t.name != t.name.lower()
    ]
    assert offenders == []
```

### 적용 범위
SQLite 는 대소문자를 가리지 않아 문제가 드러나지 않는다. **SQLite 에서
개발하고 Postgres 로 배포할 계획이라면 처음부터 지켜야 한다** — 나중에
바꾸려면 전 테이블 마이그레이션이다.

---

<a id="p-07"></a>
## P-07. 제약 위반 테스트 뒤에는 롤백이 먼저

**영역** 테스트 · SQLAlchemy

### 증상
제약조건 테스트를 추가했더니 **관계없는 테스트 9개가 연쇄로 깨졌다**. 오류는
엉뚱한 곳에서 났다: `UNIQUE constraint failed: brand.slug`.

### 원인
`pytest.raises(IntegrityError)` 로 실패를 확인한 뒤 세션이 **실패한 트랜잭션
상태**로 남는다. 이 상태에서는 후속 쿼리가 전부 거부되므로, 테이블을 비우는
정리 픽스처 자체가 동작하지 못한다. 남은 데이터가 다음 테스트를 엉뚱한
이유로 깨뜨린다.

### 해결
정리 픽스처에서 **롤백을 먼저** 한다.

```python
@pytest.fixture(autouse=True)
def _clean_tables(db: Session):
    yield
    db.rollback()          # 실패한 트랜잭션 정리 — 이게 없으면 아래가 안 돈다
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()
```

`reversed()` 는 외래키 참조 순서를 거슬러 삭제하기 위한 것이다.

### 교훈
**테스트가 무더기로 깨질 때 원인은 대개 하네스에 있다.** 개별 테스트를
고치기 전에 격리가 실제로 되는지 먼저 본다.

---

<a id="p-08"></a>
## P-08. 시드 스크립트는 존재 확인으로 멱등하게

**영역** 개발환경

### 증상
시드를 세 번 돌렸더니 판매 데이터가 284 → 568 → 852 로 불어났다.
집계 결과가 실행 횟수에 따라 달라졌다.

### 원인
마스터 데이터에는 존재 확인이 있었는데 실적 데이터에는 없었다.

### 해결
생성 블록 전체를 존재 확인으로 감싸고, 재생성은 명시적 플래그로만 허용한다.

```python
# 이미 있으면 건너뛴다. 다시 만들려면 --reset 을 쓴다.
if db.scalar(select(SalesOrder).limit(1)) is None:
    ...생성...
```

난수를 쓴다면 **시드를 고정**한다. 실행할 때마다 데이터가 달라지면 화면을
검증할 수 없다.

```python
rng = random.Random(20260813)
```

### 함께 지킬 것
개발용 계정을 만드는 스크립트는 **운영 환경에서 실행을 거부**해야 한다.
알려진 비밀번호가 운영 DB 에 들어가는 사고를 구조적으로 막는다.

```python
if settings.is_production:
    print("production 에서는 시드를 실행할 수 없습니다.", file=sys.stderr)
    raise SystemExit(1)
```

---

<a id="p-09"></a>
## P-09. CHECK 제약은 enum 에서 생성한다

**영역** 데이터

### 원인
CHECK 제약에 값 목록을 손으로 적으면 Python enum 과 두 곳에서 관리하게 되고,
언젠가 어긋난다. 어긋난 사실은 잘못된 값이 저장되고 나서야 드러난다.

### 해결
enum 에서 SQL 조각을 만든다.

```python
def check_in(column: str, enum_cls: type[StrEnum]) -> str:
    values = ", ".join(f"'{m.value}'" for m in enum_cls)
    return f"{column} IN ({values})"


class Inbound(Base):
    status: Mapped[InboundStatus] = mapped_column(String(16), ...)
    __table_args__ = (
        CheckConstraint(check_in("status", InboundStatus), name="inbound_status_valid"),
    )
```

### 왜 네이티브 ENUM 이 아닌가
PostgreSQL 네이티브 ENUM 은 값 추가에 `ALTER TYPE` 이 필요해 마이그레이션이
까다롭고, SQLite 에는 대응 개념이 없다. 문자열 + CHECK 는 양쪽에서 동일하게 동작한다.

---

<a id="p-10"></a>
## P-10. 날짜는 Date, 주차는 물리 컬럼

**영역** 데이터

### 증상 (구 코드)
날짜를 `Text` 로 저장했더니 곳곳에 방어 코드가 생겼다.

```python
snap.expiry_date.split(" ")[0]   # 시간 문자열이 섞여 들어올 수 있어서
```

범위 조회도 SQL 로 못 내려가고 파이썬 루프로 전체를 훑어야 했다.

### 해결
- **날짜는 `Date`** — 범위 조회가 인덱스를 탄다
- **ISO 주차는 `iso_year` / `iso_week` 물리 컬럼** — 주차 조회가 인덱스를 타고,
  방언별 날짜 함수(`EXTRACT`, `strftime`) 차이를 안 탄다

```python
ship_date: Mapped[date] = mapped_column(Date, nullable=False)
iso_year: Mapped[int] = mapped_column(Integer, nullable=False)
iso_week: Mapped[int] = mapped_column(Integer, nullable=False)

__table_args__ = (Index("ix_sales_order_week", "iso_year", "iso_week"),)
```

### ISO 주차는 직접 구현하지 않는다
Python 표준 라이브러리가 이미 정확하다.

```python
cal = value.isocalendar()          # (year, week, weekday)
date.fromisocalendar(2026, 25, 1)  # 그 주의 월요일
```

**연말·연초 경계가 함정이다.** 2025-12-29(월)은 달력상 2025년이지만 ISO 기준
2026년 1주차다. 직접 구현하면 12월 마지막 주 실적이 통째로 엉뚱한 해에 집계된다.
반드시 테스트로 고정한다.

---

<a id="p-11"></a>
## P-11. 동기화 대신 단일 원장에서 파생

**영역** 아키텍처

### 문제
두 시스템(SCM · 판매)을 합치면서 "양방향 동기화"를 먼저 떠올렸다. 동기화는
지연·충돌·정합성 문제를 항상 데려온다.

### 해결
같은 DB 로 합치면 동기화할 것이 없다. **원장 하나를 두고 나머지를 파생**시킨다.

```
판매 엑셀 업로드 → SalesOrder (원장, 정규화)
                     ├─ 주차 집계 → WeeklyMetric (예측 엔진 입력)
                     └─ 그대로   → 매출 대시보드
```

### 집계 테이블 설계 원칙
- **멱등하게** — 몇 번 돌려도 같은 결과. 부분 재계산(특정 주차부터)이 가능해야 한다
- **출처를 남긴다** — `source = DERIVED | IMPORTED`. 엑셀로 직접 올린 값을
  재계산이 덮어쓰면 안 된다
- **뷰가 아닌 실제 테이블** — 예측이 12주치를 반복 조회하는데 매번 원장을
  스캔하면 느리다. Materialized View 는 SQLite 에 없어 이식성도 잃는다

### 함께 배운 것
관련된 값은 **같은 행에** 둔다. 구 스키마는 `SALES_HISTORY` 와
`OUTFLOW_HISTORY` 가 분리되어 있었는데, 감모 버퍼가 *같은 주의* `출고 - 판매`라
한쪽에 행이 없는 주에 조용히 어긋났다. 하나로 합치니 문제가 사라졌다.

---

<a id="p-12"></a>
## P-12. 서버 없이 ASGI 앱 직접 호출

**영역** 테스트

### 문제 (구 코드)
E2E 스크립트가 uvicorn 을 **수동으로 띄운 상태**를 전제했고, 200 응답만
출력할 뿐 단정문이 없었다. CI 에서 돌릴 수 없고, 실패해도 통과처럼 보였다.

### 해결
`TestClient` 로 앱을 인메모리 호출한다. 포트도, 프로세스도 필요 없다.

```python
@pytest.fixture
def client():
    with TestClient(app) as c:   # with 블록이 lifespan 을 실행한다
        yield c
```

쿠키 인증이면 `TestClient` 가 쿠키를 자동 보관하므로 로그인 흐름이 그대로 검증된다.

```python
def login(client, username, password) -> str:
    res = client.post("/api/auth/login", json={...})
    assert res.status_code == 200
    return res.json()["csrf_token"]   # 세션 쿠키는 client 가 들고 있다
```

### 설정 주입 주의
설정을 import 시점에 확정하는 구조라면, **어떤 app 모듈보다 먼저** 환경변수를
세팅해야 한다. `conftest.py` 최상단에서 처리하고 그 아래 import 에 `# noqa: E402` 를 단다.

```python
import os
os.environ["EIBE_DATABASE_URL"] = f"sqlite:///{_TMP_DIR / 'test.db'}"
os.environ["EIBE_SECRET_KEY"] = "test-secret-..."

import pytest                    # noqa: E402
from app.main import app         # noqa: E402
```

### 그래도 라이브 서버를 한 번은 띄운다
TestClient 가 잡지 못하는 것이 있다 — 쿠키의 `HttpOnly` 플래그, 미들웨어 순서,
uvicorn 기동 오류. 완성 시점에 실제 서버로 한 번 훑는다.

---

<a id="p-13"></a>
## P-13. 로그인 실패 응답 시간을 맞춘다

**영역** 보안

### 원인
사용자가 없으면 비밀번호 해싱을 건너뛰게 되는데, bcrypt 는 의도적으로 느리다.
그 차이(수십~수백 ms)로 **계정 존재 여부를 알아낼 수 있다**.

### 해결
사용자가 없어도 더미 해시로 동일한 비용을 치른다.

```python
_DUMMY_HASH = hash_password("dummy-password-for-timing-equalization")

user = db.query(User).filter(User.username == payload.username).first()
password_ok = (
    verify_password(payload.password, user.password_hash)
    if user
    else verify_password(payload.password, _DUMMY_HASH)
)

if not user or not password_ok or not user.is_active:
    raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
```

**응답 메시지도 구분하지 않는다.** 테스트로 고정한다.

```python
def test_unknown_user_gives_same_message_as_wrong_password(client, db):
    wrong_pw = client.post("/api/auth/login", json={"username": "alice", ...})
    no_user  = client.post("/api/auth/login", json={"username": "ghost", ...})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["detail"] == no_user.json()["detail"]
```

### 함께 지킬 것
bcrypt 는 72바이트를 넘는 입력을 자르거나 거부한다. 긴 비밀번호는 SHA-256 으로
먼저 압축해 전체를 반영한다.

```python
def _prepare_password(password: str) -> bytes:
    raw = password.encode("utf-8")
    if len(raw) > 72:
        return hashlib.sha256(raw).hexdigest().encode("ascii")
    return raw
```

---

<a id="p-14"></a>
## P-14. 파이프라인은 실데이터로 한 번 끝까지 돌린다

**영역** 테스트

### 증상
단위 테스트 141개가 전부 통과한 상태에서, 시드 데이터로 예측 파이프라인을
돌려보니 결과가 무의미했다.

```
H12PRO   재고=0   주간수요=-44.9   평탄화=0.0   감모버퍼=-44.91
```

수요가 음수다.

### 원인
집계 함수가 **재고 스냅샷이 없는 주차의 출고량을 0으로 덮어썼다.**

```python
outflow = begin_qty + in_qty - end_qty      # 데이터가 없으면 0 + 0 - 0 = 0
metric.outflow_qty = outflow if outflow >= 0 else metric.sales_qty
```

`outflow >= 0` 이라 폴백이 걸리지 않고 0이 그대로 저장된다. 그 결과
평탄화 상수가 0이 되고, 감모 버퍼가 `0 - 판매량`이라 음수로 폭주했다.

**단위 테스트는 이걸 잡지 못했다.** 테스트마다 기초·기말 스냅샷을 둘 다
만들어줬기 때문에 "데이터가 없는" 경로를 한 번도 타지 않았다.

### 해결
1. **없는 데이터와 0인 데이터를 구분한다.** 조회 함수가 값과 함께 *어느
   스냅샷을 썼는지*를 돌려주게 하고, 판단할 수 없으면 건드리지 않는다.

```python
begin = beginning.get(key)          # None = 스냅샷 자체가 없음
end = ending.get(key)

if begin is None or end is None or begin[1] == end[1]:
    continue    # 기초·기말이 같은 스냅샷이면 그 주의 변화를 알 수 없다
```

2. **결손 경로를 테스트로 고정한다.**

```python
def test_missing_snapshots_leave_sales_derived_outflow_intact(db):
    ...판매만 있고 스냅샷은 없는 상태...
    assert apply_inventory_flow(db, week) == 0
    assert db.query(WeeklyMetric).one().outflow_qty == 80   # 덮어쓰지 않음
```

3. **시드 데이터가 실제 운영 형태를 흉내내게 한다.** 스냅샷을 한 시점만
   만들면 주차별 변화가 없어 파이프라인이 돌지 않는다. 주 1회씩 만든다.

### 교훈
단위 테스트는 **내가 상상한 입력**만 검증한다. 결손·경계 데이터는 실제
파이프라인을 끝까지 돌려봐야 드러난다. 기능 완성 시점에 시드 데이터로
전 구간을 한 번 실행하고 **숫자가 상식적인지 눈으로 본다.**

---

<a id="p-15"></a>
## P-15. 벌크 삭제는 세션 아이덴티티 맵을 정리한다

**영역** SQLAlchemy

### 증상
집계 재계산 테스트에서 경고가 났다.

```
SAWarning: Identity map already had an identity for
(<class 'WeeklyMetric'>, (1,), None), replacing it with newly flushed object.
```

### 원인
`delete(synchronize_session=False)` 는 DB 에서만 지우고 **세션의 아이덴티티
맵에는 객체를 남긴다.** SQLite 가 rowid 를 재사용하면 새로 만든 행과 식별자가
겹쳐서, 세션이 들고 있던 낡은 객체를 반환할 수 있다.

### 해결
```python
db.query(WeeklyMetric).filter(...).delete(synchronize_session="fetch")
```

`"fetch"` 는 삭제 대상을 먼저 조회해 세션 상태까지 정리한다. 약간 느리지만
"지웠는데 아직 보인다" 류의 버그를 막는다. `"evaluate"` 는 더 빠르지만
`tuple_(...).in_(...)` 같은 복잡한 조건을 처리하지 못한다.

### 언제 False 를 써도 되는가
삭제 직후 세션을 버리는 경우(요청이 끝나거나 `expunge_all()` 을 부르는 경우).
같은 세션에서 계속 작업한다면 `"fetch"` 가 안전하다.

---

<a id="p-16"></a>
## P-16. 인수인계 문서는 빈 클론에서 실행해 검증한다

**영역** 문서 · 인수인계

### 문제
"다른 PC 에서 이대로 하면 된다"고 적은 설치 절차는, **적은 사람의 PC 에서는
이미 다 갖춰져 있어서** 검증되지 않는다. 가상환경이 있고, 패키지가 깔려 있고,
`.env` 가 존재하는 상태에서 문서를 쓰기 때문이다.

### 겪은 일
STATE.md 에 설치 절차를 적고 나서 실제로 검증해 보니 **첫 명령부터 실패**했다.

```bash
git clone -q --branch feat/unified-platform <repo> /tmp/handoff-test
cd /tmp/handoff-test/eibe
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
#   UnicodeDecodeError: 'cp949' codec can't decode byte 0xe2
```

원본 저장소에서는 이미 설치가 끝나 있어 아무도 몰랐다. 절차를 문서에 적은
당사자도 몰랐다.

### 해결
빈 클론에 문서의 명령을 **한 줄씩 그대로** 실행한다. 요약하거나 건너뛰지 않는다.

```bash
git clone --branch <branch> <repo> <임시경로>
cd <임시경로>/eibe
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
cp .env.example .env
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m scripts.seed_dev
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m uvicorn app.main:app --port <빈포트>
# 로그인까지 실제로 해 본 뒤 정리
```

### 함정 — 중간 단계의 성공을 가정하지 말 것

검증 스크립트를 이렇게 짰다가 한 번 속았다.

```bash
pip install -q -r requirements.txt 2>&1 | tail -5
echo "[1] 의존성 설치 완료"      # 실패해도 무조건 출력된다
```

설치가 죽었는데 "완료"가 찍혔고, 그 다음 단계의 실패를 **다른 원인으로 오해**했다.
각 단계의 종료 코드를 확인하거나 `set -e` 를 건다.

### 마지막에 정리한다
검증용 클론과 띄운 서버는 반드시 지운다. 포트를 물고 있는 좀비 프로세스가
남으면 다음 작업에서 원인 모를 무응답으로 되돌아온다.

---

<a id="p-17"></a>
## P-17. 시드는 기능의 정상 경로를 지나가야 한다

**영역** 개발환경 · 테스트

### 증상
행사 ROI 를 붙이고 시드 데이터로 돌려보니 네 건 중 세 건이 이렇게 나왔다.

```
쿠팡 여름 특가      기간내 판매 0    리프트 -100.0%
이마트 로봇청소기 페어  기간내 판매 0    리프트 -100.0%
자사몰 브랜드데이     기간내 판매 0    리프트 -100.0%
```

예외도 경고도 없었다. 단위 테스트 55개도 전부 통과했다.

### 원인
시드가 행사 기간을 **고정 오프셋**(`monday - 6주`)으로 만들었는데, 판매는
주당 1건씩 **임의의 요일**에 찍혔다. 두 분포가 겹치지 않아 행사 기간 안에
판매가 하나도 들어오지 않았다.

```python
start = monday - timedelta(weeks=weeks_ago)      # 행사: 고정
ship_date = week_start + timedelta(days=rng.randint(0, 6))   # 판매: 무작위
```

5일짜리 행사(월~금)에 판매가 토요일에 찍히면 그 주에 판매가 있어도 기간
밖이다. **데이터는 있는데 기능이 보는 구간에는 없는** 상태다.

### 왜 위험한가
"판매 0" 은 이 기능의 **예외 경로**다. 정상 경로(리프트 계산)를 한 번도 타지
않은 채 화면이 그럴듯하게 그려지므로, 계산이 틀려도 드러나지 않는다. 실제로
이 상태에서 *시작 전 행사가 -100% 로 표시되는* 설계 결함이 묻혀 있었다 —
기간 안에 판매가 있었다면 바로 눈에 띄었을 것이다.

### 해결
시드를 **실제 데이터에 붙여서** 만든다. 좌표를 먼저 정하지 않고, 이미 있는
사실 하나를 골라 그 주변에 만든다.

```python
# 최근 판매 하나를 골라 그 날이 행사 둘째 날이 되게 붙인다.
anchor_sale = db.scalar(
    select(SalesOrder.ship_date)
    .where(
        SalesOrder.source_channel_name == channel_name,
        SalesOrder.product_id == product_id,
        SalesOrder.ship_date <= monday - timedelta(days=7),  # 기준선 14일 확보
    )
    .order_by(SalesOrder.ship_date.desc())
    .limit(1)
)
if anchor_sale is None:
    continue
start = anchor_sale - timedelta(days=1)
```

**예외 경로도 하나는 남긴다.** 다만 그것이 예외임을 이름으로 드러낸다.

```python
# 아직 시작하지 않은 행사. '시작 전'과 '진행했는데 안 팔림'을 화면이
# 구분하는지 확인하는 데 쓴다.
UPCOMING_PROMOTION = ("자사몰", "", "전체 기획전", "자사몰 브랜드데이", 4)
```

### 확인 방법
시드를 만든 뒤 **결과 분포를 눈으로 본다.** 한 값으로 몰려 있으면 의심한다.
`-100%` 가 세 줄 연속이면 그건 데이터가 아니라 시드의 모양이다.

### P-14 와 무엇이 다른가
P-14 는 *결손* 데이터(스냅샷 없음)가 파이프라인을 망가뜨린 경우다. 여기서는
데이터가 **모두 갖춰져 있고 파이프라인도 정상 동작**했다. 문제는 시드의
분포가 기능이 보는 구간과 어긋나 정상 경로를 한 번도 타지 않은 것이다.
