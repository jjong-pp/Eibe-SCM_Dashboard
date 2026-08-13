"""
ORM 기반 클래스와 공통 믹스인.

설계 규약 (SQLite ↔ PostgreSQL 이식성):
  - 테이블명은 소문자 snake_case. Postgres 는 따옴표 없는 식별자를 소문자로
    접기 때문에, 대문자 이름은 영구히 따옴표를 달고 다녀야 한다.
    (구 스키마의 USER_ACCOUNT · PRODUCT_DB 가 그 사례였다.)
  - 제약조건 이름을 규칙으로 자동 생성한다. 이름 없는 제약은 Alembic 이
    되돌릴 수 없고, SQLite 의 batch ALTER 도 실패한다.
  - 날짜는 Date/DateTime, 금액은 Numeric. Text 에 담지 않는다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Alembic 이 제약조건을 식별할 수 있도록 이름 규칙을 고정한다.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    """타임존을 인지하는 현재 시각.

    SQLite 는 timestamptz 가 없어 naive 로 저장되지만, 애플리케이션은 항상
    UTC 를 기준으로 다루므로 Postgres 전환 시 값이 그대로 유효하다.
    """
    return datetime.now(UTC)


class TimestampMixin:
    """생성·수정 시각. 감사 추적의 최소 단위."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
