"""테스트용 객체 생성 헬퍼."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.dates import iso_week_of
from app.models.enums import BrandCategory, WarehouseType
from app.models.master import Brand, Channel, Product, ProductAlias, Warehouse
from app.models.sales import Promotion, SalesOrder


def make_brand(
    db: Session,
    name: str = "드리미",
    slug: str = "dreame",
    category: BrandCategory = BrandCategory.ELECTRONICS,
) -> Brand:
    brand = Brand(name=name, slug=slug, category=category)
    db.add(brand)
    db.commit()
    db.refresh(brand)
    return brand


def make_product(
    db: Session,
    brand: Brand,
    product_code: str = "P-001",
    name: str = "테스트 품목",
    pack_qty_per_tu: int = 24,
    purchase_price: Decimal | str = "10.5000",
) -> Product:
    product = Product(
        product_code=product_code,
        name=name,
        brand_id=brand.id,
        pack_qty_per_tu=pack_qty_per_tu,
        purchase_price=Decimal(purchase_price),
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def make_warehouse(
    db: Session,
    name: str = "용인 메인",
    type_: WarehouseType = WarehouseType.HUB,
) -> Warehouse:
    warehouse = Warehouse(name=name, type=type_)
    db.add(warehouse)
    db.commit()
    db.refresh(warehouse)
    return warehouse


def make_channel(
    db: Session,
    name: str = "쿠팡",
    channel_group: str | None = "온라인",
    warehouse: Warehouse | None = None,
    is_major: bool = True,
) -> Channel:
    channel = Channel(
        name=name,
        channel_group=channel_group,
        warehouse_id=warehouse.id if warehouse else None,
        is_major=is_major,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


def make_alias(
    db: Session,
    product: Product,
    source_name: str,
    lineup_name: str | None = None,
) -> ProductAlias:
    alias = ProductAlias(
        source_name=source_name, product_id=product.id, lineup_name=lineup_name
    )
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return alias


def make_promotion(
    db: Session,
    brand: Brand,
    start_date: date,
    end_date: date,
    source_channel_name: str = "쿠팡",
    source_product_name: str | None = "드리미 H12 Pro",
    event_name: str = "여름 특가",
    slot_name: str | None = "메인 배너",
) -> Promotion:
    promotion = Promotion(
        brand_id=brand.id,
        start_date=start_date,
        end_date=end_date,
        source_channel_name=source_channel_name,
        source_product_name=source_product_name,
        event_name=event_name,
        slot_name=slot_name,
    )
    db.add(promotion)
    db.commit()
    db.refresh(promotion)
    return promotion


def make_sales_order(
    db: Session,
    brand: Brand,
    ship_date: date,
    qty: int = 10,
    amount: Decimal | str = "100000.00",
    product: Product | None = None,
    channel: Channel | None = None,
    source_product_name: str = "드리미 H12 Pro",
    source_channel_name: str = "쿠팡",
    order_no: str | None = None,
) -> SalesOrder:
    week = iso_week_of(ship_date)
    order = SalesOrder(
        brand_id=brand.id,
        order_no=order_no,
        source_product_name=source_product_name,
        source_channel_name=source_channel_name,
        product_id=product.id if product else None,
        channel_id=channel.id if channel else None,
        ship_date=ship_date,
        iso_year=week.year,
        iso_week=week.week,
        qty=qty,
        amount=Decimal(amount),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order
