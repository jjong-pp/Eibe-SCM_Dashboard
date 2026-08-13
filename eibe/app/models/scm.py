"""
공급망 — 발주 · 입고 · 재고 · 발주 계획.

구 스키마에서 달라진 점:
  - PRODUCTION_DB 제거. 발주-생산-인보이스 3단계 매칭은 이미 폐기된 기능이고
    (구 문서 7.16), 생산코드는 입고 레코드의 단순 필드로 충분하다.
  - 날짜가 Text → Date. 문자열 날짜 때문에 `expiry_date.split(" ")[0]` 같은
    방어 코드가 곳곳에 필요했고 범위 조회를 파이썬 루프로 돌아야 했다.
  - 금액이 Float → Numeric. 재고 자산 합산에서 오차가 누적되면 안 된다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import InboundStatus, PlanStatus, check_in
from app.models.master import Product, Warehouse
from app.models.types import Money, Rate, UnitPrice


class PurchaseOrder(Base, TimestampMixin):
    """발주. 계획(MonthlyOrderPlan)이 확정되어 실제로 나간 주문."""

    __tablename__ = "purchase_order"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_month: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), nullable=False)
    order_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    product: Mapped[Product] = relationship()

    __table_args__ = (
        CheckConstraint("order_qty > 0", name="purchase_order_qty_positive"),
        Index("ix_purchase_order_month_product", "order_month", "product_id"),
    )


class Inbound(Base, TimestampMixin):
    """입고 (인보이스 통합).

    재고 자산 평가의 원가 기준이 여기서 나온다. 마스터의 예상 단가가 아니라
    실제 결제한 원화 금액(payment_amount_krw)을 역추적하는 것이 원칙이다.
    """

    __tablename__ = "inbound"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── 식별 정보 ────────────────────────────────────────────────────
    invoice_no: Mapped[str | None] = mapped_column(String(64), default=None)
    bl_no: Mapped[str | None] = mapped_column(String(64), default=None)
    purchase_code: Mapped[str | None] = mapped_column(String(64), default=None)
    production_code: Mapped[str | None] = mapped_column(String(64), default=None)

    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), nullable=False)
    arrival_warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouse.id"), default=None
    )

    # ── 일정 ─────────────────────────────────────────────────────────
    shipping_date: Mapped[date | None] = mapped_column(Date, default=None)
    korea_arrival_date: Mapped[date | None] = mapped_column(Date, default=None)
    eta: Mapped[date | None] = mapped_column(Date, default=None)
    manufacture_date: Mapped[date | None] = mapped_column(Date, default=None)
    # 전자제품 브랜드에서는 화면상 '보증기한'으로 표기된다.
    expiry_date: Mapped[date | None] = mapped_column(Date, default=None)

    # ── 수량 ─────────────────────────────────────────────────────────
    carton_qty: Mapped[int | None] = mapped_column(Integer, default=None)
    unit_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ── 금액 ─────────────────────────────────────────────────────────
    unit_price: Mapped[Decimal | None] = mapped_column(UnitPrice, default=None)
    total_price: Mapped[Decimal | None] = mapped_column(Money, default=None)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Rate, default=None)
    payment_amount_krw: Mapped[Decimal | None] = mapped_column(
        Money, default=None
    )
    invoice_date: Mapped[date | None] = mapped_column(Date, default=None)
    payment_date: Mapped[date | None] = mapped_column(Date, default=None)

    status: Mapped[InboundStatus] = mapped_column(
        String(16), default=InboundStatus.DEPARTED, nullable=False
    )

    product: Mapped[Product] = relationship()
    arrival_warehouse: Mapped[Warehouse | None] = relationship()

    __table_args__ = (
        CheckConstraint(check_in("status", InboundStatus), name="inbound_status_valid"),
        CheckConstraint("unit_qty >= 0", name="inbound_unit_qty_non_negative"),
        Index("ix_inbound_status", "status"),
        Index("ix_inbound_product_id", "product_id"),
        Index("ix_inbound_eta", "eta"),
        Index("ix_inbound_expiry_date", "expiry_date"),
    )

    @property
    def is_received(self) -> bool:
        return self.status == InboundStatus.RECEIVED

    def __repr__(self) -> str:
        return f"<Inbound {self.invoice_no or self.id} {self.status}>"


class InventorySnapshot(Base, TimestampMixin):
    """시점별 재고. 같은 (일자, 창고, 품목, 유통기한)은 한 건만 존재한다.

    유통기한을 키에 포함하는 이유: FEFO 관리를 하려면 같은 품목이라도
    로트별로 잔량을 구분해야 한다.
    """

    __tablename__ = "inventory_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouse.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, default=None)
    qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    warehouse: Mapped[Warehouse] = relationship()
    product: Mapped[Product] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "snapshot_date",
            "warehouse_id",
            "product_id",
            "expiry_date",
            name="uq_inventory_snapshot_lot",
        ),
        CheckConstraint("qty >= 0", name="inventory_snapshot_qty_non_negative"),
        Index("ix_inventory_snapshot_date_product", "snapshot_date", "product_id"),
        Index("ix_inventory_snapshot_warehouse_id", "warehouse_id"),
    )


class MonthlyOrderPlan(Base, TimestampMixin):
    """월별 발주 계획.

    발주 규칙상 리드타임을 고려해 6개월 뒤 도착분을 주문한다. 그래서
    target_month(발주월)와 arrival_month(도착월)를 분리해 들고 있다.
    """

    __tablename__ = "monthly_order_plan"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    target_month: Mapped[str] = mapped_column(String(7), nullable=False)   # YYYY-MM
    arrival_month: Mapped[str | None] = mapped_column(String(7), default=None)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), nullable=False)

    system_suggested_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    user_modified_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[PlanStatus] = mapped_column(
        String(16), default=PlanStatus.DRAFT, nullable=False
    )
    # 낙관적 잠금 — 다른 사용자가 먼저 수정했으면 409 로 되돌린다.
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    product: Mapped[Product] = relationship()

    __table_args__ = (
        UniqueConstraint("target_month", "product_id", name="uq_monthly_order_plan"),
        CheckConstraint(check_in("status", PlanStatus), name="monthly_order_plan_status_valid"),
        CheckConstraint("system_suggested_qty >= 0", name="monthly_order_plan_suggested_non_negative"),
        CheckConstraint("user_modified_qty >= 0", name="monthly_order_plan_modified_non_negative"),
        Index("ix_monthly_order_plan_arrival_month", "arrival_month"),
    )
