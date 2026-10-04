"""
DB 엔진 · 세션 관리.

SQLite 와 PostgreSQL 양쪽에서 동일하게 동작하도록 방언별 차이를 여기서만 처리한다.
전환 시 바뀌는 것은 `.env` 의 EIBE_DATABASE_URL 한 줄뿐이다.
"""

from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

engine: Engine = create_engine(
    settings.DATABASE_URL,
    **settings.sqlalchemy_kwargs(),
)


if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        """SQLite 전용 설정.

        PostgreSQL 은 외래키를 항상 강제하고 WAL 개념이 없으므로 SQLite 에서만 건다.
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 의존성 — 요청당 세션 하나.

    예외 발생 시 롤백한다. 구 버전은 롤백 없이 close 만 해서
    실패한 트랜잭션이 커넥션에 남을 수 있었다.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
