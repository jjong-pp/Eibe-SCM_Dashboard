"""
주차별 집계 — 수요 예측의 입력.

구 스키마의 SALES_HISTORY 와 OUTFLOW_HISTORY 를 한 테이블로 합쳤다.
감모 버퍼가 `같은 주의 출고량 - 판매량`으로 계산되는데, 두 테이블로 나뉘어
있으면 주차를 맞춰 조인해야 하고 한쪽만 존재하는 주가 생기면 조용히 어긋난다.

이 테이블은 **파생 데이터**다. 판매 원장(SalesOrder)과 재고 스냅샷에서
언제든 재계산할 수 있어야 하며, 재계산은 멱등해야 한다. 다만 엑셀로 직접
올린 값(source=IMPORTED)은 재계산이 덮어쓰지 않는다.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.dates import IsoWeek
from app.models.base import Base, TimestampMixin
from app.models.enums import MetricSource, check_in
from app.models.master import Product, Warehouse
from app.models.types import Money


class WeeklyMetric(Base, TimestampMixin):
    """(주차 × 품목 × 창고) 단위 실적."""

    __tablename__ = "weekly_metric"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    iso_year: Mapped[int] = mapped_column(Integer, nullable=False)
    iso_week: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouse.id"), nullable=False)

    # ── 재고 흐름 ────────────────────────────────────────────────────
    beginning_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ending_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    inbound_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 단순 출고량 = 기초 + 입고 - 기말. 예측의 평탄화 상수가 이 값에서 나온다.
    outflow_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ── 출고 구성 ────────────────────────────────────────────────────
    # 감모 버퍼 = 평균(outflow_qty - sales_qty). 즉 판매로 설명되지 않는 감소분.
    sales_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    loss_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transfer_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    sales_amount: Mapped[Decimal] = mapped_column(
        Money, default=Decimal("0"), nullable=False
    )

    source: Mapped[MetricSource] = mapped_column(
        String(16), default=MetricSource.DERIVED, nullable=False
    )

    product: Mapped[Product] = relationship()
    warehouse: Mapped[Warehouse] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "iso_year", "iso_week", "product_id", "warehouse_id", name="uq_weekly_metric"
        ),
        CheckConstraint("iso_week BETWEEN 1 AND 53", name="weekly_metric_iso_week_range"),
        CheckConstraint(check_in("source", MetricSource), name="weekly_metric_source_valid"),
        CheckConstraint("beginning_qty >= 0", name="weekly_metric_beginning_non_negative"),
        CheckConstraint("ending_qty >= 0", name="weekly_metric_ending_non_negative"),
        # 집계 순서(오래된 것부터)로 읽는 질의가 대부분이라 복합 인덱스를 둔다.
        Index("ix_weekly_metric_product_week", "product_id", "iso_year", "iso_week"),
        Index("ix_weekly_metric_week", "iso_year", "iso_week"),
        Index("ix_weekly_metric_warehouse_id", "warehouse_id"),
    )

    @property
    def week(self) -> IsoWeek:
        return IsoWeek(self.iso_year, self.iso_week)

    @property
    def unexplained_qty(self) -> int:
        """판매로 설명되지 않는 출고분. 감모 버퍼의 원재료."""
        return self.outflow_qty - self.sales_qty

    def __repr__(self) -> str:
        return (
            f"<WeeklyMetric {self.iso_year}-W{self.iso_week:02d} "
            f"p={self.product_id} w={self.warehouse_id}>"
        )
