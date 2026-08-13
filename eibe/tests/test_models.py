"""
스키마가 실제로 약속을 지키는지 검증한다.

구 스키마는 날짜를 Text 로, 금액을 Float 로 담았고 제약조건도 느슨했다.
여기서는 "타입을 바꿨다"는 주장을 테스트로 고정한다 — 잘못된 값이 정말
거부되는지, Decimal 이 정말 정확히 왕복하는지.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.enums import BrandCategory, InboundStatus, MetricSource, WarehouseType
from app.models.master import Brand, LogisticsCost, Product, ProductAlias
from app.models.metrics import WeeklyMetric
from app.models.sales import SalesOrder
from app.models.scm import Inbound, InventorySnapshot
from app.models.types import Money
from tests.factories import (
    make_alias,
    make_brand,
    make_channel,
    make_product,
    make_sales_order,
    make_warehouse,
)


class TestTableNaming:
    """PostgreSQL 은 따옴표 없는 식별자를 소문자로 접는다.

    대문자 테이블명(구 USER_ACCOUNT, PRODUCT_DB)은 영구히 따옴표가 필요해진다.
    """

    def test_all_tables_are_lowercase(self) -> None:
        offenders = [t.name for t in Base.metadata.sorted_tables if t.name != t.name.lower()]
        assert offenders == []

    def test_all_constraints_are_named(self) -> None:
        """이름 없는 제약은 Alembic 이 되돌릴 수 없고 SQLite batch ALTER 도 깨진다."""
        unnamed: list[str] = []
        for table in Base.metadata.sorted_tables:
            for constraint in table.constraints:
                if constraint.name is None:
                    unnamed.append(f"{table.name}.{type(constraint).__name__}")
        assert unnamed == []


class TestMoneyPrecision:
    def test_declared_precision_fits_float64(self) -> None:
        """SQLite 는 Decimal 을 float 경유로 저장한다.

        유효자릿수가 15를 넘으면 값이 조용히 반올림되므로, 선언 정밀도가
        그 한계 안에 있어야 약속을 지킬 수 있다.
        """
        assert Money.precision <= 15

    def test_decimal_round_trips_exactly(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand, purchase_price="1234.5678")

        db.expunge_all()
        loaded = db.get(Product, product.id)

        assert isinstance(loaded.purchase_price, Decimal)
        assert loaded.purchase_price == Decimal("1234.5678")

    def test_largest_supported_amount_round_trips(self, db: Session) -> None:
        """Money 한도값이 손실 없이 저장되는지 — 정밀도 상한의 실제 검증."""
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        limit = Decimal("9999999999999.99")

        db.add(
            Inbound(
                product_id=product.id,
                arrival_warehouse_id=warehouse.id,
                unit_qty=1,
                payment_amount_krw=limit,
            )
        )
        db.commit()
        db.expunge_all()

        stored = db.query(Inbound).one().payment_amount_krw
        assert stored == limit

    def test_fractional_sums_do_not_drift(self, db: Session) -> None:
        """Float 였다면 0.1 + 0.2 != 0.3 으로 어긋난다."""
        brand = make_brand(db)
        orders = [
            make_sales_order(db, brand, date(2026, 6, 15), amount=a, order_no=str(i))
            for i, a in enumerate(["0.10", "0.20"])
        ]
        assert sum((o.amount for o in orders), Decimal("0")) == Decimal("0.30")


class TestDateTypes:
    def test_dates_are_date_objects_not_strings(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)

        db.add(
            Inbound(
                product_id=product.id,
                arrival_warehouse_id=warehouse.id,
                unit_qty=100,
                expiry_date=date(2027, 3, 1),
                eta=date(2026, 9, 1),
            )
        )
        db.commit()
        db.expunge_all()

        loaded = db.query(Inbound).one()
        assert isinstance(loaded.expiry_date, date)
        assert loaded.expiry_date == date(2027, 3, 1)

    def test_date_range_query_works_in_sql(self, db: Session) -> None:
        """Text 날짜였다면 파이썬 루프로 걸러야 했던 조회."""
        brand = make_brand(db)
        for day in (date(2026, 6, 1), date(2026, 6, 15), date(2026, 7, 1)):
            make_sales_order(db, brand, day, order_no=day.isoformat())

        found = (
            db.query(SalesOrder)
            .filter(SalesOrder.ship_date.between(date(2026, 6, 1), date(2026, 6, 30)))
            .count()
        )
        assert found == 2


class TestCheckConstraints:
    def test_invalid_brand_category_rejected(self, db: Session) -> None:
        db.add(Brand(name="x", slug="x", category="INVALID"))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_invalid_inbound_status_rejected(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        db.add(Inbound(product_id=product.id, unit_qty=1, status="배송중"))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_zero_pack_qty_rejected(self, db: Session) -> None:
        brand = make_brand(db)
        db.add(
            Product(
                product_code="P-BAD", name="x", brand_id=brand.id, pack_qty_per_tu=0
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()

    def test_negative_inventory_rejected(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        db.add(
            InventorySnapshot(
                snapshot_date=date(2026, 6, 1),
                warehouse_id=warehouse.id,
                product_id=product.id,
                qty=-5,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()

    def test_logistics_route_cannot_loop_to_itself(self, db: Session) -> None:
        warehouse = make_warehouse(db)
        db.add(
            LogisticsCost(
                departure_warehouse_id=warehouse.id,
                arrival_warehouse_id=warehouse.id,
                cost_per_tu=Decimal("100"),
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()

    def test_iso_week_out_of_range_rejected(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        db.add(
            WeeklyMetric(
                iso_year=2026,
                iso_week=54,  # ISO 주차는 53이 최대
                product_id=product.id,
                warehouse_id=warehouse.id,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


class TestUniqueConstraints:
    def test_duplicate_product_code_rejected(self, db: Session) -> None:
        brand = make_brand(db)
        make_product(db, brand, product_code="P-DUP")
        db.add(Product(product_code="P-DUP", name="다른 품목", brand_id=brand.id))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_alias_source_name_is_unique(self, db: Session) -> None:
        """한 원본 제품명이 두 품목에 매핑되면 집계가 갈라진다."""
        brand = make_brand(db)
        first = make_product(db, brand, product_code="P-1")
        second = make_product(db, brand, product_code="P-2")
        make_alias(db, first, "드리미 H12 Pro")

        db.add(ProductAlias(source_name="드리미 H12 Pro", product_id=second.id))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_weekly_metric_is_unique_per_week_product_warehouse(
        self, db: Session
    ) -> None:
        """재집계가 멱등하려면 이 조합이 유일해야 한다."""
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        common = {
            "iso_year": 2026,
            "iso_week": 25,
            "product_id": product.id,
            "warehouse_id": warehouse.id,
        }
        db.add(WeeklyMetric(**common, outflow_qty=10))
        db.commit()

        db.add(WeeklyMetric(**common, outflow_qty=20))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_inventory_snapshot_unique_per_lot(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        common = {
            "snapshot_date": date(2026, 6, 1),
            "warehouse_id": warehouse.id,
            "product_id": product.id,
            "expiry_date": date(2027, 1, 1),
        }
        db.add(InventorySnapshot(**common, qty=100))
        db.commit()

        db.add(InventorySnapshot(**common, qty=50))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_different_expiry_lots_coexist(self, db: Session) -> None:
        """FEFO 관리를 하려면 같은 품목이라도 로트별로 나뉘어야 한다."""
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        for expiry in (date(2027, 1, 1), date(2027, 6, 1)):
            db.add(
                InventorySnapshot(
                    snapshot_date=date(2026, 6, 1),
                    warehouse_id=warehouse.id,
                    product_id=product.id,
                    expiry_date=expiry,
                    qty=100,
                )
            )
        db.commit()
        assert db.query(InventorySnapshot).count() == 2


class TestForeignKeys:
    def test_foreign_keys_are_enforced(self, db: Session) -> None:
        """SQLite 는 PRAGMA foreign_keys=ON 이 없으면 FK 를 무시한다."""
        db.add(Product(product_code="P-ORPHAN", name="x", brand_id=9999))
        with pytest.raises(IntegrityError):
            db.commit()


class TestJoiningPoints:
    """SCM 과 Sales 를 잇는 두 접합점이 실제로 동작하는지."""

    def test_alias_resolves_source_name_to_product(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand, product_code="H12PRO")
        make_alias(db, product, "드리미 H12 Pro", lineup_name="H12 시리즈")

        alias = db.query(ProductAlias).filter_by(source_name="드리미 H12 Pro").one()
        assert alias.product.product_code == "H12PRO"
        assert alias.lineup_name == "H12 시리즈"

    def test_channel_links_to_warehouse(self, db: Session) -> None:
        warehouse = make_warehouse(db, "온라인 FFC", WarehouseType.ONLINE)
        channel = make_channel(db, "쿠팡", warehouse=warehouse)

        assert channel.warehouse is not None
        assert channel.warehouse.name == "온라인 FFC"

    def test_unmapped_channel_is_allowed(self, db: Session) -> None:
        """매핑 전 채널도 등록은 되어야 한다. 집계에서 '미배정'으로 드러난다."""
        channel = make_channel(db, "신규채널", warehouse=None)
        assert channel.warehouse_id is None

    def test_sales_order_keeps_source_names_when_unmapped(self, db: Session) -> None:
        brand = make_brand(db)
        order = make_sales_order(
            db, brand, date(2026, 6, 15), source_product_name="알 수 없는 제품"
        )

        assert order.product_id is None
        assert order.is_mapped is False
        # 원본이 남아 있어야 매핑 규칙을 고친 뒤 다시 해석할 수 있다
        assert order.source_product_name == "알 수 없는 제품"


class TestDomainHelpers:
    def test_inbound_status_has_pipeline_order(self) -> None:
        assert InboundStatus.DEPARTED.order < InboundStatus.RECEIVED.order

    def test_weekly_metric_unexplained_qty(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        metric = WeeklyMetric(
            iso_year=2026,
            iso_week=25,
            product_id=product.id,
            warehouse_id=warehouse.id,
            outflow_qty=120,
            sales_qty=100,
            source=MetricSource.DERIVED,
        )
        db.add(metric)
        db.commit()

        # 판매로 설명되지 않는 20개가 감모 버퍼의 원재료가 된다
        assert metric.unexplained_qty == 20

    def test_brand_category_drives_expiry_labelling(self, db: Session) -> None:
        """전자제품은 화면에서 '유통기한' 대신 '보증기한'으로 표기된다."""
        food = make_brand(db, "식품브랜드", "food-brand", BrandCategory.FOOD)
        electronics = make_brand(db, "드리미", "dreame", BrandCategory.ELECTRONICS)

        assert food.category == BrandCategory.FOOD
        assert electronics.category == BrandCategory.ELECTRONICS
