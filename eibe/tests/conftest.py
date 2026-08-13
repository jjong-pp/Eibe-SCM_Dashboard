"""
pytest 공통 픽스처.

구 버전 테스트는 uvicorn 을 수동으로 띄워야 했고 단정문도 없었다. 여기서는
ASGI 앱을 인메모리로 직접 호출하므로 서버 기동이 필요 없다.

주의: app.config 는 import 시점에 설정을 확정하므로, 어떤 app 모듈보다
먼저 환경변수를 세팅해야 한다.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path

# ── app 패키지 import 이전에 테스트용 환경 구성 ──────────────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="eibe-test-"))

os.environ["EIBE_ENV"] = "local"
os.environ["EIBE_DEBUG"] = "false"
os.environ["EIBE_LOG_LEVEL"] = "WARNING"
os.environ["EIBE_DATABASE_URL"] = f"sqlite:///{_TMP_DIR / 'test.db'}"
os.environ["EIBE_SECRET_KEY"] = "test-secret-key-not-used-outside-tests-0123456789"
os.environ["EIBE_BOOTSTRAP_ADMIN_PASSWORD"] = ""  # 부트스트랩 비활성화

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.auth import Role, User  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Generator[None, None, None]:
    """테스트 스키마 생성.

    Alembic 이 아닌 create_all 을 쓰는 이유: 테스트는 마이그레이션 이력이
    아니라 최종 스키마를 검증한다. 마이그레이션 자체의 검증은 별도 테스트에서.
    """
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    shutil.rmtree(_TMP_DIR, ignore_errors=True)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _clean_tables(db: Session) -> Generator[None, None, None]:
    """테스트 간 격리 — 매 테스트 후 모든 테이블을 비운다.

    제약조건 위반을 검증하는 테스트는 세션을 실패한 트랜잭션 상태로 남긴다.
    먼저 롤백하지 않으면 정리 자체가 실패하고, 남은 데이터가 다음 테스트를
    엉뚱한 이유로 깨뜨린다.
    """
    yield
    db.rollback()
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


def make_user(
    db: Session,
    username: str = "tester",
    password: str = "test-password-123",
    role: Role = Role.VIEWER,
) -> User:
    user = User(
        username=username,
        password_hash=hash_password(password),
        name=username,
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def login(client: TestClient, username: str, password: str) -> str:
    """로그인 후 CSRF 토큰을 반환한다. 세션 쿠키는 client 에 자동 보관된다."""
    res = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert res.status_code == 200, res.text
    return res.json()["csrf_token"]


@pytest.fixture
def csrf_header() -> Generator[dict[str, str], None, None]:
    """CSRF 헤더를 만드는 헬퍼를 쓰기 쉽게 노출."""
    yield {}


__all__ = ["make_user", "login", "settings"]
