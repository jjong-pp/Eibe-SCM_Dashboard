"""
ORM 모델 등록 지점.

Alembic autogenerate 와 create_all 이 모든 테이블을 인식하려면 여기서
모든 모델 모듈을 import 해야 한다. 구 버전의 `from app.models import *`
같은 와일드카드는 쓰지 않는다 — 이름 출처가 불분명해지고 린터가 잡지 못한다.
"""

from app.models.auth import Role, User
from app.models.base import Base, TimestampMixin, utcnow

__all__ = [
    "Base",
    "Role",
    "TimestampMixin",
    "User",
    "utcnow",
]
