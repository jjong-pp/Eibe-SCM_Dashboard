"""사용자 계정 및 권한."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.types import EnumStr


class Role(StrEnum):
    """권한 3단계.

    구 SCM 의 ADMIN/OPERATOR 와 Sales Hub 의 admin/viewer 를 통합한 것.
      ADMIN    — 마스터·사용자·시스템 설정 변경
      OPERATOR — 업무 데이터 등록/수정 (재고·입고·발주·판매)
      VIEWER   — 조회 전용
    """

    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self]

    def can_act_as(self, required: Role) -> bool:
        """상위 권한은 하위 권한을 포함한다."""
        return self.rank >= required.rank


_ROLE_RANK: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.OPERATOR: 1,
    Role.ADMIN: 2,
}


class User(Base, TimestampMixin):
    __tablename__ = "user_account"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, default=None)

    # Enum 을 네이티브 타입이 아닌 문자열 + CHECK 로 저장한다.
    # Postgres 네이티브 ENUM 은 값 추가 시 마이그레이션이 까다롭다.
    role: Mapped[Role] = mapped_column(
        EnumStr(Role), default=Role.VIEWER, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "role IN ('ADMIN', 'OPERATOR', 'VIEWER')",
            name="user_role_valid",
        ),
    )

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"
