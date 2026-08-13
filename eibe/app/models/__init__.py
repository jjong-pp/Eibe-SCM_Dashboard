"""
ORM 모델 등록 지점.

Alembic autogenerate 와 create_all 이 모든 테이블을 인식하려면 여기서
모든 모델 모듈을 import 해야 한다. 구 버전의 `from app.models import *`
같은 와일드카드는 쓰지 않는다 — 이름 출처가 불분명해지고 린터가 잡지 못한다.
"""

from app.models.auth import Role, User
from app.models.base import Base, TimestampMixin, utcnow
from app.models.enums import (
    BrandCategory,
    InboundStatus,
    MetricSource,
    OutflowType,
    PlanStatus,
    WarehouseType,
)
from app.models.master import (
    Brand,
    Channel,
    LogisticsCost,
    Product,
    ProductAlias,
    Warehouse,
    WarehouseProductMoq,
)
from app.models.metrics import WeeklyMetric
from app.models.sales import Promotion, SalesOrder
from app.models.scm import Inbound, InventorySnapshot, MonthlyOrderPlan, PurchaseOrder

__all__ = [
    # 기반
    "Base",
    "TimestampMixin",
    "utcnow",
    # 열거형
    "BrandCategory",
    "InboundStatus",
    "MetricSource",
    "OutflowType",
    "PlanStatus",
    "Role",
    "WarehouseType",
    # 인증
    "User",
    # 기준 정보
    "Brand",
    "Channel",
    "LogisticsCost",
    "Product",
    "ProductAlias",
    "Warehouse",
    "WarehouseProductMoq",
    # 공급망
    "Inbound",
    "InventorySnapshot",
    "MonthlyOrderPlan",
    "PurchaseOrder",
    # 판매
    "Promotion",
    "SalesOrder",
    # 집계
    "WeeklyMetric",
]
