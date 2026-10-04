"""
기준 정보 — 브랜드 · 품목 · 창고 · 채널.

SCM 과 Sales Hub 의 접합점이 여기에 있다:
  ProductAlias    Sales 의 원본 제품명 → SCM 품목      (구 `lineup` 시트)
  Channel         Sales 의 판매 채널  → SCM 창고        (구 `channelGroup` 시트)

이 둘만 연결되면 나머지 도메인은 서로를 몰라도 된다.
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

from app.models.base import Base, TimestampMixin
from app.models.enums import BrandCategory, WarehouseType, check_in
from app.models.types import EnumStr, Money, UnitPrice


class Brand(Base, TimestampMixin):
    """브랜드.

    구 SCM 은 브랜드를 Product 의 문자열 컬럼(brand_category)으로만 들고
    있었고, Sales Hub 는 별도 브랜드 개념(드리미)을 썼다. 둘을 하나의
    엔티티로 합치고, 식품/전자 구분은 category 속성으로 남긴다.
    """

    __tablename__ = "brand"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # URL·API 에서 쓰는 안정적인 식별자 (구 Sales Hub 의 slugifyBrand 대체)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    category: Mapped[BrandCategory] = mapped_column(
        EnumStr(BrandCategory), default=BrandCategory.FOOD, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    products: Mapped[list[Product]] = relationship(back_populates="brand")

    __table_args__ = (
        CheckConstraint(check_in("category", BrandCategory), name="brand_category_valid"),
    )

    def __repr__(self) -> str:
        return f"<Brand {self.slug}>"


class Product(Base, TimestampMixin):
    """품목. product_code 가 업무상 식별자이며 변경하지 않는다."""

    __tablename__ = "product"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brand.id"), nullable=False)

    # 카툰(TU)당 입수량. 발주 수량을 규격화할 때 최소 단위로 쓴다.
    pack_qty_per_tu: Mapped[int] = mapped_column(Integer, default=24, nullable=False)

    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    # 금액은 Float 이 아닌 Numeric. 자산 평가액을 합산하므로 오차가 누적되면 안 된다.
    purchase_price: Mapped[Decimal] = mapped_column(
        UnitPrice, default=Decimal("0"), nullable=False
    )

    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    brand: Mapped[Brand] = relationship(back_populates="products")
    aliases: Mapped[list[ProductAlias]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("pack_qty_per_tu > 0", name="product_pack_qty_positive"),
        CheckConstraint("purchase_price >= 0", name="product_price_non_negative"),
        Index("ix_product_brand_id", "brand_id"),
    )

    def __repr__(self) -> str:
        return f"<Product {self.product_code}>"


class ProductAlias(Base, TimestampMixin):
    """판매 데이터의 제품명을 품목에 연결한다.

    채널마다 같은 제품을 다르게 표기하므로(`드리미 H12 Pro` / `H12PRO 무선청소기`)
    원본 문자열을 그대로 두고 매핑만 관리한다. 구 Sales Hub 의 `lineup` 시트가
    하던 일이며, 매핑되지 않은 원본은 업로드 시 경고로 드러난다.
    """

    __tablename__ = "product_alias"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 판매 원장에 실제로 찍히는 문자열
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), nullable=False)
    # 대시보드에 묶어 보여줄 라인업명 (구 `라인업명` 컬럼)
    lineup_name: Mapped[str | None] = mapped_column(String(255), default=None)

    product: Mapped[Product] = relationship(back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("source_name", name="uq_product_alias_source_name"),
        Index("ix_product_alias_product_id", "product_id"),
    )

    def __repr__(self) -> str:
        return f"<ProductAlias {self.source_name!r} -> {self.product_id}>"


class Warehouse(Base, TimestampMixin):
    """물류 거점. 창고명은 업무상 식별자라 변경하지 않는다."""

    __tablename__ = "warehouse"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    type: Mapped[WarehouseType] = mapped_column(
        EnumStr(WarehouseType), default=WarehouseType.ONLINE, nullable=False
    )
    # 이 창고가 받아줄 수 있는 잔여 유통기한 하한 (일)
    allowed_expiry_days: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    # 기본 이관 최소 수량. 품목별 예외는 WarehouseProductMoq 로 덮어쓴다.
    default_transfer_moq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    channels: Mapped[list[Channel]] = relationship(back_populates="warehouse")

    __table_args__ = (
        CheckConstraint(check_in("type", WarehouseType), name="warehouse_type_valid"),
        CheckConstraint(
            "allowed_expiry_days >= 0", name="warehouse_expiry_days_non_negative"
        ),
    )

    def __repr__(self) -> str:
        return f"<Warehouse {self.name}>"


class Channel(Base, TimestampMixin):
    """판매 채널.

    warehouse_id 가 SCM 쪽 접합점이다. 채널 매출이 어느 거점의 재고를
    소진시키는지 알아야 출고량과 재고일수를 이어붙일 수 있다. 아직 매핑되지
    않은 채널은 NULL 로 두고, 집계에서 '미배정'으로 드러낸다.
    """

    __tablename__ = "channel"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    # 여러 채널을 묶어 보는 상위 그룹 (구 `채널 그룹` 컬럼)
    channel_group: Mapped[str | None] = mapped_column(String(128), default=None)
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouse.id"), default=None
    )
    # 대시보드 기본 노출 대상 (구 `주요채널` 시트)
    is_major: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    warehouse: Mapped[Warehouse | None] = relationship(back_populates="channels")

    __table_args__ = (
        Index("ix_channel_channel_group", "channel_group"),
        Index("ix_channel_warehouse_id", "warehouse_id"),
    )

    def __repr__(self) -> str:
        return f"<Channel {self.name}>"


class WarehouseProductMoq(Base, TimestampMixin):
    """창고·품목별 이관 최소 수량 예외."""

    __tablename__ = "warehouse_product_moq"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouse.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), nullable=False)
    transfer_moq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("warehouse_id", "product_id", name="uq_warehouse_product_moq"),
        CheckConstraint("transfer_moq >= 0", name="warehouse_product_moq_non_negative"),
    )


class LogisticsCost(Base, TimestampMixin):
    """구간별 물류비 (출발 창고 → 도착 창고, 카툰당)."""

    __tablename__ = "logistics_cost"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    departure_warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse.id"), nullable=False
    )
    arrival_warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse.id"), nullable=False
    )
    cost_per_tu: Mapped[Decimal] = mapped_column(
        Money, default=Decimal("0"), nullable=False
    )

    departure_warehouse: Mapped[Warehouse] = relationship(
        foreign_keys=[departure_warehouse_id]
    )
    arrival_warehouse: Mapped[Warehouse] = relationship(
        foreign_keys=[arrival_warehouse_id]
    )

    __table_args__ = (
        UniqueConstraint(
            "departure_warehouse_id", "arrival_warehouse_id", name="uq_logistics_route"
        ),
        CheckConstraint(
            "departure_warehouse_id <> arrival_warehouse_id",
            name="logistics_cost_distinct_endpoints",
        ),
        CheckConstraint("cost_per_tu >= 0", name="logistics_cost_non_negative"),
    )
