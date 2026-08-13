"""
파생 집계 검증.

가장 중요한 성질은 **멱등성**이다. 재계산을 몇 번 돌려도 값이 같아야 한다.
집계가 실행 횟수에 따라 달라지면 예측 결과를 믿을 수 없다.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.dates import iso_week_of
from app.models.enums import MetricSource, WarehouseType
from app.models.metrics import WeeklyMetric
from app.models.scm import Inbound, InventorySnapshot
from app.services.derive import (
    apply_inventory_flow,
    load_history,
    rebuild_for_orders,
    rebuild_weekly_metrics,
    resolve_sales_mappings,
    unmapped_sources,
)
from tests.factories import (
    make_alias,
    make_brand,
    make_channel,
    make_product,
    make_sales_order,
    make_warehouse,
)

MONDAY = date(2026, 6, 15)  # 2026-W25


class TestIdempotency:
    def test_rebuilding_twice_gives_identical_rows(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        channel = make_channel(db, warehouse=warehouse)
        make_sales_order(db, brand, MONDAY, qty=10, amount="1000", product=product, channel=channel)

        first = rebuild_weekly_metrics(db)
        rows_after_first = db.query(WeeklyMetric).count()
        totals_first = db.query(WeeklyMetric).one().sales_qty

        second = rebuild_weekly_metrics(db)
        rows_after_second = db.query(WeeklyMetric).count()
        totals_second = db.query(WeeklyMetric).one().sales_qty

        assert rows_after_first == rows_after_second == 1
        assert totals_first == totals_second == 10
        assert first.rows_written == second.rows_written

    def test_three_rebuilds_do_not_accumulate(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        channel = make_channel(db, warehouse=warehouse)
        for offset in range(5):
            make_sales_order(
                db,
                brand,
                MONDAY + timedelta(days=offset),
                qty=10,
                product=product,
                channel=channel,
                order_no=f"O-{offset}",
            )

        counts = []
        for _ in range(3):
            rebuild_weekly_metrics(db)
            counts.append(db.query(WeeklyMetric).one().sales_qty)

        assert counts == [50, 50, 50]


class TestAggregation:
    def test_sums_qty_and_amount_within_a_week(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        channel = make_channel(db, warehouse=warehouse)

        for offset, qty in enumerate([3, 4, 5]):
            make_sales_order(
                db, brand, MONDAY + timedelta(days=offset), qty=qty,
                amount="100.50", product=product, channel=channel, order_no=f"O-{offset}",
            )

        rebuild_weekly_metrics(db)
        metric = db.query(WeeklyMetric).one()

        assert metric.sales_qty == 12
        assert metric.sales_amount == Decimal("301.50")

    def test_separate_weeks_stay_separate(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        channel = make_channel(db, warehouse=warehouse)

        make_sales_order(db, brand, MONDAY, qty=10, product=product, channel=channel, order_no="A")
        make_sales_order(
            db, brand, MONDAY + timedelta(days=7), qty=20,
            product=product, channel=channel, order_no="B",
        )

        rebuild_weekly_metrics(db)
        assert db.query(WeeklyMetric).count() == 2

    def test_channels_sharing_a_warehouse_are_combined(self, db: Session) -> None:
        """채널이 달라도 같은 창고 재고를 소진하면 한 행으로 합쳐진다."""
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        coupang = make_channel(db, "쿠팡", warehouse=warehouse)
        naver = make_channel(db, "네이버", warehouse=warehouse)

        make_sales_order(db, brand, MONDAY, qty=10, product=product, channel=coupang, order_no="A")
        make_sales_order(db, brand, MONDAY, qty=15, product=product, channel=naver, order_no="B")

        rebuild_weekly_metrics(db)
        metric = db.query(WeeklyMetric).one()
        assert metric.sales_qty == 25

    def test_different_warehouses_stay_separate(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        hub = make_warehouse(db, "용인 메인", WarehouseType.HUB)
        online = make_warehouse(db, "온라인 FFC", WarehouseType.ONLINE)

        make_sales_order(
            db, brand, MONDAY, qty=10, product=product,
            channel=make_channel(db, "직영", warehouse=hub), order_no="A",
        )
        make_sales_order(
            db, brand, MONDAY, qty=15, product=product,
            channel=make_channel(db, "쿠팡", warehouse=online), order_no="B",
        )

        rebuild_weekly_metrics(db)
        assert db.query(WeeklyMetric).count() == 2


class TestUnmappedHandling:
    def test_unmapped_orders_are_excluded(self, db: Session) -> None:
        """창고를 특정할 수 없으면 재고 지표에 넣을 수 없다."""
        brand = make_brand(db)
        make_sales_order(db, brand, MONDAY, qty=10)  # product/channel 둘 다 없음

        result = rebuild_weekly_metrics(db)
        assert result.rows_written == 0
        assert db.query(WeeklyMetric).count() == 0

    def test_unmapped_sources_are_reported(self, db: Session) -> None:
        """조용히 사라지지 않고 목록으로 드러나야 한다."""
        brand = make_brand(db)
        make_sales_order(
            db, brand, MONDAY,
            source_product_name="알 수 없는 제품",
            source_channel_name="새 채널",
        )

        pending = unmapped_sources(db)
        assert "알 수 없는 제품" in pending["products"]
        assert "새 채널" in pending["channels"]

    def test_adding_an_alias_later_resolves_existing_orders(self, db: Session) -> None:
        """원본을 보존한 덕분에 재업로드 없이 다시 해석된다."""
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        make_channel(db, "쿠팡", warehouse=warehouse)

        order = make_sales_order(
            db, brand, MONDAY, qty=10,
            source_product_name="드리미 H12 Pro", source_channel_name="쿠팡",
        )
        assert order.product_id is None

        # 뒤늦게 별칭을 등록한다
        make_alias(db, product, "드리미 H12 Pro")
        updated = resolve_sales_mappings(db)

        assert updated == 1
        db.refresh(order)
        assert order.product_id == product.id
        assert order.channel_id is not None

        rebuild_weekly_metrics(db)
        assert db.query(WeeklyMetric).one().sales_qty == 10


class TestImportedRowsArePreserved:
    def test_rebuild_does_not_overwrite_imported_rows(self, db: Session) -> None:
        """엑셀로 직접 올린 값은 재계산이 건드리지 않는다."""
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        channel = make_channel(db, warehouse=warehouse)
        make_sales_order(db, brand, MONDAY, qty=10, product=product, channel=channel)

        week = iso_week_of(MONDAY)
        db.add(
            WeeklyMetric(
                iso_year=week.year,
                iso_week=week.week,
                product_id=product.id,
                warehouse_id=warehouse.id,
                sales_qty=9999,
                source=MetricSource.IMPORTED,
            )
        )
        db.commit()

        result = rebuild_weekly_metrics(db)

        assert result.rows_preserved == 1
        assert db.query(WeeklyMetric).one().sales_qty == 9999

    def test_derived_rows_are_replaced(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        channel = make_channel(db, warehouse=warehouse)
        make_sales_order(db, brand, MONDAY, qty=10, product=product, channel=channel)

        rebuild_weekly_metrics(db)
        metric = db.query(WeeklyMetric).one()
        metric.sales_qty = 1  # 손으로 훼손
        db.commit()

        rebuild_weekly_metrics(db)
        assert db.query(WeeklyMetric).one().sales_qty == 10


class TestPartialRebuild:
    def test_range_limits_which_weeks_are_touched(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        channel = make_channel(db, warehouse=warehouse)

        week_a = MONDAY
        week_b = MONDAY + timedelta(days=7)
        make_sales_order(db, brand, week_a, qty=10, product=product, channel=channel, order_no="A")
        make_sales_order(db, brand, week_b, qty=20, product=product, channel=channel, order_no="B")

        result = rebuild_weekly_metrics(db, since=week_b, until=week_b)

        assert result.weeks_covered == 1
        assert db.query(WeeklyMetric).count() == 1
        assert db.query(WeeklyMetric).one().sales_qty == 20

    def test_rebuild_for_orders_covers_only_their_weeks(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        channel = make_channel(db, warehouse=warehouse)

        make_sales_order(db, brand, MONDAY, qty=10, product=product, channel=channel, order_no="OLD")
        rebuild_weekly_metrics(db)

        fresh = [
            make_sales_order(
                db, brand, MONDAY + timedelta(days=7), qty=20,
                product=product, channel=channel, order_no="NEW",
            )
        ]
        result = rebuild_for_orders(db, fresh)

        assert result.weeks_covered == 1
        # 기존 주차는 그대로 남아 있어야 한다
        assert db.query(WeeklyMetric).count() == 2

    def test_empty_order_list_is_a_no_op(self, db: Session) -> None:
        result = rebuild_for_orders(db, [])
        assert result.rows_written == 0

    def test_no_sales_data_is_not_an_error(self, db: Session) -> None:
        result = rebuild_weekly_metrics(db)
        assert result.weeks_covered == 0


class TestInventoryFlow:
    def test_outflow_derived_from_stock_movement(self, db: Session) -> None:
        """단순출고량 = 기초 + 입고 - 기말."""
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        channel = make_channel(db, warehouse=warehouse)
        week = iso_week_of(MONDAY)

        make_sales_order(db, brand, MONDAY, qty=80, product=product, channel=channel)
        rebuild_weekly_metrics(db)

        db.add_all([
            InventorySnapshot(
                snapshot_date=week.start_date(), warehouse_id=warehouse.id,
                product_id=product.id, qty=1000,
            ),
            InventorySnapshot(
                snapshot_date=week.end_date(), warehouse_id=warehouse.id,
                product_id=product.id, qty=900,
            ),
        ])
        db.commit()

        apply_inventory_flow(db, week)
        metric = db.query(WeeklyMetric).one()

        assert metric.beginning_qty == 1000
        assert metric.ending_qty == 900
        assert metric.outflow_qty == 100
        # 100 나갔는데 80만 팔렸다 → 20개가 감모 버퍼의 원재료
        assert metric.unexplained_qty == 20

    def test_inbound_within_week_counts(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        channel = make_channel(db, warehouse=warehouse)
        week = iso_week_of(MONDAY)

        make_sales_order(db, brand, MONDAY, qty=50, product=product, channel=channel)
        rebuild_weekly_metrics(db)

        db.add_all([
            InventorySnapshot(
                snapshot_date=week.start_date(), warehouse_id=warehouse.id,
                product_id=product.id, qty=1000,
            ),
            InventorySnapshot(
                snapshot_date=week.end_date(), warehouse_id=warehouse.id,
                product_id=product.id, qty=1400,
            ),
            Inbound(
                product_id=product.id, arrival_warehouse_id=warehouse.id,
                unit_qty=500, eta=week.start_date() + timedelta(days=2),
            ),
        ])
        db.commit()

        apply_inventory_flow(db, week)
        metric = db.query(WeeklyMetric).one()

        # 1000 + 500 - 1400 = 100
        assert metric.inbound_qty == 500
        assert metric.outflow_qty == 100

    def test_missing_snapshots_leave_sales_derived_outflow_intact(
        self, db: Session
    ) -> None:
        """스냅샷이 없는 주차를 0으로 덮어쓰면 예측이 무너진다.

        평탄화 상수가 0이 되고, 감모 버퍼가 `0 - 판매량`이라 음수로 폭주한다.
        실데이터로 파이프라인을 돌려보고서야 드러난 문제다.
        """
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        channel = make_channel(db, warehouse=warehouse)
        week = iso_week_of(MONDAY)

        make_sales_order(db, brand, MONDAY, qty=80, product=product, channel=channel)
        rebuild_weekly_metrics(db)

        updated = apply_inventory_flow(db, week)  # 스냅샷이 하나도 없다

        assert updated == 0
        assert db.query(WeeklyMetric).one().outflow_qty == 80

    def test_single_snapshot_is_not_enough_to_infer_movement(
        self, db: Session
    ) -> None:
        """기초와 기말이 같은 스냅샷을 가리키면 변화량을 알 수 없다."""
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        channel = make_channel(db, warehouse=warehouse)
        week = iso_week_of(MONDAY)

        make_sales_order(db, brand, MONDAY, qty=80, product=product, channel=channel)
        rebuild_weekly_metrics(db)

        db.add(
            InventorySnapshot(
                snapshot_date=week.start_date(), warehouse_id=warehouse.id,
                product_id=product.id, qty=1000,
            )
        )
        db.commit()

        assert apply_inventory_flow(db, week) == 0
        assert db.query(WeeklyMetric).one().outflow_qty == 80

    def test_negative_movement_falls_back_to_sales(self, db: Session) -> None:
        """스냅샷 누락으로 재고가 늘어난 것처럼 보이면 판매량을 쓴다."""
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        channel = make_channel(db, warehouse=warehouse)
        week = iso_week_of(MONDAY)

        make_sales_order(db, brand, MONDAY, qty=50, product=product, channel=channel)
        rebuild_weekly_metrics(db)

        db.add_all([
            InventorySnapshot(
                snapshot_date=week.start_date(), warehouse_id=warehouse.id,
                product_id=product.id, qty=100,
            ),
            InventorySnapshot(
                snapshot_date=week.end_date(), warehouse_id=warehouse.id,
                product_id=product.id, qty=900,  # 입고 기록 없이 증가
            ),
        ])
        db.commit()

        apply_inventory_flow(db, week)
        assert db.query(WeeklyMetric).one().outflow_qty == 50


class TestLoadHistory:
    def test_returns_weeks_in_chronological_order(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        channel = make_channel(db, warehouse=warehouse)

        for week_offset in range(4):
            make_sales_order(
                db, brand, MONDAY - timedelta(weeks=week_offset),
                qty=(week_offset + 1) * 10,
                product=product, channel=channel, order_no=f"W{week_offset}",
            )
        rebuild_weekly_metrics(db)

        outflow, sales = load_history(db, product.id, iso_week_of(MONDAY), weeks=4)

        # 가장 오래된 주(40)부터 최근 주(10)까지
        assert sales == [40, 30, 20, 10]
        assert len(outflow) == len(sales)

    def test_missing_weeks_are_skipped_not_zero_filled(self, db: Session) -> None:
        """데이터 없는 주를 0으로 채우면 소진율을 과소평가한다."""
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        channel = make_channel(db, warehouse=warehouse)

        make_sales_order(db, brand, MONDAY, qty=100, product=product, channel=channel)
        rebuild_weekly_metrics(db)

        outflow, sales = load_history(db, product.id, iso_week_of(MONDAY), weeks=12)

        assert sales == [100]  # 12개가 아니라 1개

    def test_warehouses_are_summed(self, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        hub = make_warehouse(db, "용인 메인", WarehouseType.HUB)
        online = make_warehouse(db, "온라인 FFC", WarehouseType.ONLINE)

        make_sales_order(
            db, brand, MONDAY, qty=10, product=product,
            channel=make_channel(db, "직영", warehouse=hub), order_no="A",
        )
        make_sales_order(
            db, brand, MONDAY, qty=15, product=product,
            channel=make_channel(db, "쿠팡", warehouse=online), order_no="B",
        )
        rebuild_weekly_metrics(db)

        _, sales = load_history(db, product.id, iso_week_of(MONDAY), weeks=2)
        assert sales == [25]
