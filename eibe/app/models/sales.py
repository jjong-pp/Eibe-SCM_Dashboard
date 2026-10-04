"""
판매 — 주문 원장 · 행사.

구 Sales Hub 는 엑셀 시트를 그대로(한글 컬럼명 문자열 배열) 보관했다.
여기서는 정규화하되 **원본 문자열을 함께 남긴다**:

  source_product_name / source_channel_name 은 업로드된 값 그대로다.
  product_id / channel_id 는 매핑을 거친 해석 결과이며, 매핑이 없으면 NULL 이다.

이렇게 두면 매핑 규칙이 바뀌었을 때 원본에서 다시 해석할 수 있고,
미매핑 건이 조용히 사라지지 않고 집계에서 드러난다.
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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.master import Brand, Channel, Product
from app.models.types import Money, Percent


class SalesOrder(Base, TimestampMixin):
    """판매 주문 원장.

    SCM 의 주차 집계(WeeklyMetric)가 이 테이블에서 파생되므로, 별도의
    동기화 작업 없이 판매 실적이 수요 예측에 반영된다.
    """

    __tablename__ = "sales_order"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brand.id"), nullable=False)

    # ── 원본 값 (업로드된 그대로) ────────────────────────────────────
    order_no: Mapped[str | None] = mapped_column(String(128), default=None)
    source_product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_channel_name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str | None] = mapped_column(String(128), default=None)

    # ── 해석 결과 (매핑 실패 시 NULL) ────────────────────────────────
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("product.id"), default=None
    )
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channel.id"), default=None
    )

    # ── 일자 ─────────────────────────────────────────────────────────
    order_date: Mapped[date | None] = mapped_column(Date, default=None)
    # 집계 기준일. 재고가 실제로 빠져나간 시점이라 출고일을 쓴다.
    ship_date: Mapped[date] = mapped_column(Date, nullable=False)

    # ISO 주차를 물리 컬럼으로 저장한다. 주차 조회가 인덱스를 타고,
    # 방언별 날짜 함수 차이에도 영향을 받지 않는다.
    iso_year: Mapped[int] = mapped_column(Integer, nullable=False)
    iso_week: Mapped[int] = mapped_column(Integer, nullable=False)

    # ── 수량 · 금액 ──────────────────────────────────────────────────
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Money, default=None)
    amount: Mapped[Decimal] = mapped_column(
        Money, default=Decimal("0"), nullable=False
    )

    brand: Mapped[Brand] = relationship()
    product: Mapped[Product | None] = relationship()
    channel: Mapped[Channel | None] = relationship()

    __table_args__ = (
        CheckConstraint("iso_week BETWEEN 1 AND 53", name="sales_order_iso_week_range"),
        Index("ix_sales_order_week", "iso_year", "iso_week"),
        Index("ix_sales_order_ship_date", "ship_date"),
        Index("ix_sales_order_brand_week", "brand_id", "iso_year", "iso_week"),
        Index("ix_sales_order_product_id", "product_id"),
        Index("ix_sales_order_channel_id", "channel_id"),
        # 미매핑 건을 빠르게 찾기 위한 인덱스
        Index("ix_sales_order_source_product_name", "source_product_name"),
    )

    @property
    def is_mapped(self) -> bool:
        return self.product_id is not None and self.channel_id is not None

    def __repr__(self) -> str:
        return f"<SalesOrder {self.order_no or self.id} {self.ship_date}>"


class Promotion(Base, TimestampMixin):
    """행사(프로모션).

    매출 변동의 원인을 설명할 때 쓴다 — 특정 주에 판매가 튀었다면 그 주에
    걸려 있던 행사를 함께 보여준다.
    """

    __tablename__ = "promotion"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brand.id"), nullable=False)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    # ── 원본 값 ──────────────────────────────────────────────────────
    source_product_name: Mapped[str | None] = mapped_column(String(255), default=None)
    source_channel_name: Mapped[str | None] = mapped_column(String(128), default=None)

    # ── 해석 결과 ────────────────────────────────────────────────────
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("product.id"), default=None
    )
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channel.id"), default=None
    )

    # ── 행사 내용 ────────────────────────────────────────────────────
    slot_name: Mapped[str | None] = mapped_column(String(255), default=None)
    event_name: Mapped[str | None] = mapped_column(String(255), default=None)
    list_price: Mapped[Decimal | None] = mapped_column(Money, default=None)
    price: Mapped[Decimal | None] = mapped_column(Money, default=None)
    discount_rate: Mapped[Decimal | None] = mapped_column(Percent, default=None)
    reward_points: Mapped[Decimal | None] = mapped_column(Money, default=None)
    gift: Mapped[str | None] = mapped_column(String(255), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    is_marketing: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_confirmed: Mapped[bool] = mapped_column(default=False, nullable=False)

    brand: Mapped[Brand] = relationship()
    product: Mapped[Product | None] = relationship()
    channel: Mapped[Channel | None] = relationship()

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="promotion_date_order"),
        Index("ix_promotion_period", "start_date", "end_date"),
        Index("ix_promotion_brand_id", "brand_id"),
        Index("ix_promotion_product_id", "product_id"),
    )

    def covers(self, day: date) -> bool:
        return self.start_date <= day <= self.end_date

    def __repr__(self) -> str:
        return f"<Promotion {self.event_name or self.id}>"
