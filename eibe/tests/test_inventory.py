"""
재고 서비스 · API 테스트.

여기서 고정하는 판단:
  - 재고일수 구간은 forecasting 의 상수 하나만 쓴다 (화면 범례와 어긋나면 안 된다)
  - FEFO 는 **앞에 쌓인 물량까지 합쳐** 소진 시점을 본다
  - 근거가 없으면 위험이라고 말하지 않는다 (is_judgeable)
  - 무한대는 JSON 으로 나가지 않는다
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.auth import Role
from app.models.enums import MetricSource, WarehouseType
from app.models.metrics import WeeklyMetric
from app.models.scm import InventorySnapshot
from app.services import forecasting, inventory
from tests.conftest import sign_in
from tests.factories import make_brand, make_channel, make_product, make_warehouse

MONDAY = date(2026, 6, 15)


def add_snapshot(
    db: Session, product, warehouse, day: date, qty: int, expiry: date | None = None
) -> InventorySnapshot:
    snapshot = InventorySnapshot(
        snapshot_date=day,
        warehouse_id=warehouse.id,
        product_id=product.id,
        expiry_date=expiry,
        qty=qty,
    )
    db.add(snapshot)
    db.commit()
    return snapshot


def add_metric(
    db: Session, product, warehouse, day: date, outflow: int, sales: int
) -> None:
    from app.core.dates import iso_week_of

    week = iso_week_of(day)
    db.add(
        WeeklyMetric(
            iso_year=week.year,
            iso_week=week.week,
            product_id=product.id,
            warehouse_id=warehouse.id,
            outflow_qty=outflow,
            sales_qty=sales,
            source=MetricSource.DERIVED,
        )
    )
    db.commit()


@pytest.fixture
def world(db: Session):
    brand = make_brand(db)
    hub = make_warehouse(db, name="용인 메인", type_=WarehouseType.HUB)
    ffc = make_warehouse(db, name="온라인 FFC", type_=WarehouseType.ONLINE)
    product = make_product(db, brand, product_code="H12", name="H12 Pro")
    make_channel(db, name="쿠팡", warehouse=ffc)
    return {"brand": brand, "hub": hub, "ffc": ffc, "product": product}


class TestStockSummary:
    def test_weeks_of_supply_drives_the_risk_band(
        self, db: Session, world: dict
    ) -> None:
        """재고 200, 주간수요 50 → 4주 → 6주 미만이므로 위험."""
        add_snapshot(db, world["product"], world["ffc"], MONDAY, 200)
        for offset in range(1, 5):
            add_metric(
                db, world["product"], world["ffc"],
                MONDAY - timedelta(weeks=offset), outflow=50, sales=50,
            )

        position = inventory.stock_summary(db, as_of=MONDAY)[0]
        assert position.qty == 200
        assert position.weekly_demand == pytest.approx(50.0)
        assert position.weeks_of_supply == pytest.approx(4.0)
        assert position.risk is forecasting.StockRisk.HIGH

    @pytest.mark.parametrize(
        ("qty", "expected"),
        [
            (200, forecasting.StockRisk.HIGH),   # 4주
            (350, forecasting.StockRisk.MID),    # 7주
            (550, forecasting.StockRisk.LOW),    # 11주
            (900, forecasting.StockRisk.SAFE),   # 18주
        ],
    )
    def test_all_four_bands_are_reachable(
        self, db: Session, world: dict, qty: int, expected
    ) -> None:
        add_snapshot(db, world["product"], world["ffc"], MONDAY, qty)
        for offset in range(1, 5):
            add_metric(
                db, world["product"], world["ffc"],
                MONDAY - timedelta(weeks=offset), outflow=50, sales=50,
            )
        assert inventory.stock_summary(db, as_of=MONDAY)[0].risk is expected

    def test_zero_demand_reports_infinite_supply(
        self, db: Session, world: dict
    ) -> None:
        """소진되지 않는 재고는 0으로 나누지 않고 '소진 불가'로 둔다."""
        add_snapshot(db, world["product"], world["hub"], MONDAY, 500)

        position = inventory.stock_summary(db, as_of=MONDAY)[0]
        assert math.isinf(position.weeks_of_supply)
        assert position.is_depletable is False
        assert position.risk is forecasting.StockRisk.SAFE

    def test_company_wide_view_sums_the_warehouses(
        self, db: Session, world: dict
    ) -> None:
        add_snapshot(db, world["product"], world["hub"], MONDAY, 300)
        add_snapshot(db, world["product"], world["ffc"], MONDAY, 200)

        positions = inventory.stock_summary(db, as_of=MONDAY, by_warehouse=False)
        assert len(positions) == 1
        assert positions[0].qty == 500
        assert positions[0].warehouse_id is None

    def test_snapshot_date_used_is_reported(self, db: Session, world: dict) -> None:
        """오래된 스냅샷으로 계산했는지 화면이 알 수 있어야 한다."""
        add_snapshot(db, world["product"], world["ffc"], MONDAY - timedelta(days=30), 100)

        position = inventory.stock_summary(db, as_of=MONDAY)[0]
        assert position.snapshot_date == MONDAY - timedelta(days=30)

    def test_electronics_brand_uses_warranty_wording(
        self, db: Session, world: dict
    ) -> None:
        add_snapshot(db, world["product"], world["ffc"], MONDAY, 100)
        assert inventory.stock_summary(db, as_of=MONDAY)[0].expiry_label == "보증기한"


class TestExpiryReport:
    def test_fefo_counts_the_stock_ahead_of_each_lot(
        self, db: Session, world: dict
    ) -> None:
        """뒤 로트는 앞의 것이 다 빠진 뒤에야 소진되기 시작한다."""
        product, ffc = world["product"], world["ffc"]
        add_snapshot(db, product, ffc, MONDAY, 100, expiry=MONDAY + timedelta(days=60))
        add_snapshot(db, product, ffc, MONDAY, 100, expiry=MONDAY + timedelta(days=400))
        for offset in range(1, 5):
            add_metric(db, product, ffc, MONDAY - timedelta(weeks=offset), 50, 50)

        lots = inventory.expiry_report(db, as_of=MONDAY)
        first, second = lots[0], lots[1]

        assert first.qty_ahead == 0
        assert first.weeks_to_clear == pytest.approx(2.0)   # 100 / 50
        assert second.qty_ahead == 100
        assert second.weeks_to_clear == pytest.approx(4.0)  # (100+100) / 50

    def test_lot_that_cannot_clear_in_time_is_flagged(
        self, db: Session, world: dict
    ) -> None:
        product, ffc = world["product"], world["ffc"]
        # 500개, 주간 50개 → 10주(70일) 걸리는데 기한은 30일 남았다.
        add_snapshot(db, product, ffc, MONDAY, 500, expiry=MONDAY + timedelta(days=30))
        for offset in range(1, 5):
            add_metric(db, product, ffc, MONDAY - timedelta(weeks=offset), 50, 50)

        lot = inventory.expiry_report(db, as_of=MONDAY)[0]
        assert lot.is_at_risk is True
        assert lot.is_judgeable is True

    def test_lot_that_clears_in_time_is_not_flagged(
        self, db: Session, world: dict
    ) -> None:
        product, ffc = world["product"], world["ffc"]
        add_snapshot(db, product, ffc, MONDAY, 100, expiry=MONDAY + timedelta(days=90))
        for offset in range(1, 5):
            add_metric(db, product, ffc, MONDAY - timedelta(weeks=offset), 50, 50)

        assert inventory.expiry_report(db, as_of=MONDAY)[0].is_at_risk is False

    def test_expired_lot_is_risk_even_without_demand_history(
        self, db: Session, world: dict
    ) -> None:
        """이미 지난 기한은 소진율과 무관하게 사실이다."""
        add_snapshot(
            db, world["product"], world["hub"], MONDAY, 100,
            expiry=MONDAY - timedelta(days=1),
        )
        lot = inventory.expiry_report(db, as_of=MONDAY)[0]
        assert lot.is_at_risk is True
        assert lot.is_judgeable is True

    def test_no_consumption_history_means_unjudged_not_safe(
        self, db: Session, world: dict
    ) -> None:
        """용인 메인창고처럼 판매 채널이 없는 거점은 판정할 근거가 없다.

        근거 없이 위험으로 칠하면 화면이 전부 빨개져 진짜 위험이 묻힌다.
        """
        add_snapshot(
            db, world["product"], world["hub"], MONDAY, 100,
            expiry=MONDAY + timedelta(days=30),
        )
        lot = inventory.expiry_report(db, as_of=MONDAY)[0]
        assert lot.is_judgeable is False
        assert lot.is_at_risk is False

    def test_lot_without_expiry_is_not_judged(
        self, db: Session, world: dict
    ) -> None:
        add_snapshot(db, world["product"], world["ffc"], MONDAY, 100)
        for offset in range(1, 5):
            add_metric(db, world["product"], world["ffc"], MONDAY - timedelta(weeks=offset), 50, 50)

        lot = inventory.expiry_report(db, as_of=MONDAY)[0]
        assert lot.days_remaining is None
        assert lot.is_judgeable is False
        assert lot.is_at_risk is False

    def test_at_risk_filter(self, db: Session, world: dict) -> None:
        product, ffc = world["product"], world["ffc"]
        add_snapshot(db, product, ffc, MONDAY, 500, expiry=MONDAY + timedelta(days=10))
        add_snapshot(db, product, ffc, MONDAY, 100, expiry=MONDAY + timedelta(days=900))
        for offset in range(1, 5):
            add_metric(db, product, ffc, MONDAY - timedelta(weeks=offset), 50, 50)

        assert len(inventory.expiry_report(db, as_of=MONDAY)) == 2
        assert len(inventory.expiry_report(db, as_of=MONDAY, at_risk_only=True)) == 1


class TestTransferPlan:
    def test_shortfall_is_topped_up_from_the_hub(
        self, db: Session, world: dict
    ) -> None:
        product, hub, ffc = world["product"], world["hub"], world["ffc"]
        add_snapshot(db, product, hub, MONDAY, 5000)
        add_snapshot(db, product, ffc, MONDAY, 100)  # 2주치
        for offset in range(1, 5):
            add_metric(db, product, ffc, MONDAY - timedelta(weeks=offset), 50, 50)

        plan = inventory.simulate_transfers(db, as_of=MONDAY, target_weeks=9.0)
        assert len(plan.suggestions) == 1
        suggestion = plan.suggestions[0]
        # 목표 9주 × 50 = 450, 현재 100 → 350 부족
        assert suggestion.shortage_qty == 350
        assert suggestion.suggested_qty == 350
        assert suggestion.limited_by_hub is False

    def test_hub_stock_caps_the_suggestion(self, db: Session, world: dict) -> None:
        product, hub, ffc = world["product"], world["hub"], world["ffc"]
        add_snapshot(db, product, hub, MONDAY, 120)
        add_snapshot(db, product, ffc, MONDAY, 100)
        for offset in range(1, 5):
            add_metric(db, product, ffc, MONDAY - timedelta(weeks=offset), 50, 50)

        plan = inventory.simulate_transfers(db, as_of=MONDAY, target_weeks=9.0)
        suggestion = plan.suggestions[0]
        assert suggestion.suggested_qty == 120
        assert suggestion.limited_by_hub is True
        assert plan.shortfalls  # 못 채운 것이 드러나야 한다

    def test_warehouse_with_enough_stock_is_left_alone(
        self, db: Session, world: dict
    ) -> None:
        product, hub, ffc = world["product"], world["hub"], world["ffc"]
        add_snapshot(db, product, hub, MONDAY, 5000)
        add_snapshot(db, product, ffc, MONDAY, 1000)  # 20주치
        for offset in range(1, 5):
            add_metric(db, product, ffc, MONDAY - timedelta(weeks=offset), 50, 50)

        assert inventory.simulate_transfers(db, as_of=MONDAY).suggestions == []

    def test_warehouse_without_demand_is_not_topped_up(
        self, db: Session, world: dict
    ) -> None:
        """소진되지 않는 거점에 보내면 그대로 묵힌다."""
        add_snapshot(db, world["product"], world["hub"], MONDAY, 5000)
        add_snapshot(db, world["product"], world["ffc"], MONDAY, 0)

        assert inventory.simulate_transfers(db, as_of=MONDAY).suggestions == []

    def test_no_hub_yields_an_empty_plan(self, db: Session) -> None:
        brand = make_brand(db)
        ffc = make_warehouse(db, name="온라인 FFC", type_=WarehouseType.ONLINE)
        product = make_product(db, brand)
        add_snapshot(db, product, ffc, MONDAY, 10)

        plan = inventory.simulate_transfers(db, as_of=MONDAY)
        assert plan.hub_warehouse_id is None
        assert plan.suggestions == []


class TestInventoryApi:
    def test_reads_require_login(self, client: TestClient) -> None:
        assert client.get("/api/inventory/summary").status_code == 401
        assert client.get("/api/inventory/expiry").status_code == 401
        assert client.get("/api/inventory/transfer-plan").status_code == 401

    def test_viewer_cannot_post_a_snapshot(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.VIEWER)
        res = client.post(
            "/api/inventory/snapshots",
            json={
                "snapshot_date": "2026-06-15",
                "warehouse_id": world["ffc"].id,
                "product_id": world["product"].id,
                "qty": 10,
            },
            headers=headers,
        )
        assert res.status_code == 403

    def test_operator_can_post_a_snapshot(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        res = client.post(
            "/api/inventory/snapshots",
            json={
                "snapshot_date": "2026-06-15",
                "warehouse_id": world["ffc"].id,
                "product_id": world["product"].id,
                "qty": 10,
            },
            headers=headers,
        )
        assert res.status_code == 201
        assert res.json()["warehouse_name"] == "온라인 FFC"

    def test_reposting_the_same_lot_updates_it(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        payload = {
            "snapshot_date": "2026-06-15",
            "warehouse_id": world["ffc"].id,
            "product_id": world["product"].id,
            "qty": 10,
        }
        client.post("/api/inventory/snapshots", json=payload, headers=headers)
        client.post(
            "/api/inventory/snapshots", json={**payload, "qty": 99}, headers=headers
        )

        listed = client.get("/api/inventory/snapshots").json()
        assert len(listed) == 1
        assert listed[0]["qty"] == 99

    def test_negative_qty_is_rejected(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        res = client.post(
            "/api/inventory/snapshots",
            json={
                "snapshot_date": "2026-06-15",
                "warehouse_id": world["ffc"].id,
                "product_id": world["product"].id,
                "qty": -5,
            },
            headers=headers,
        )
        assert res.status_code == 422

    def test_summary_carries_the_threshold_legend(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        """화면 범례가 상수를 따로 들고 있으면 서버 기준과 조용히 어긋난다."""
        sign_in(client, db, Role.VIEWER)
        body = client.get("/api/inventory/summary").json()
        assert body["thresholds_weeks"] == [6.0, 9.0, 13.0]

    def test_infinite_supply_is_serialised_as_null(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        """JSON 에 Infinity 를 실어보내면 파서마다 다르게 처리한다."""
        add_snapshot(db, world["product"], world["hub"], MONDAY, 500)
        sign_in(client, db, Role.VIEWER)

        body = client.get(f"/api/inventory/summary?as_of={MONDAY}").json()
        position = body["positions"][0]
        assert position["weeks_of_supply"] is None
        assert position["risk"] == "risk-safe"
        assert "Infinity" not in client.get(f"/api/inventory/summary?as_of={MONDAY}").text

    def test_expiry_endpoint_counts_both_states(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        add_snapshot(
            db, world["product"], world["hub"], MONDAY, 100,
            expiry=MONDAY + timedelta(days=30),
        )
        sign_in(client, db, Role.VIEWER)

        body = client.get(f"/api/inventory/expiry?as_of={MONDAY}").json()
        assert body["at_risk_count"] == 0
        assert body["unjudged_count"] == 1
