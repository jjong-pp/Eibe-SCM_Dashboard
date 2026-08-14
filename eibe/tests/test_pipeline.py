"""
입고 파이프라인 · 발주 계획 테스트.

업무 규칙 중 여기서 고정하는 것:
  - 발주는 **6개월 뒤 도착분**을 주문한다 (발주월 ≠ 도착월)
  - 확정된 계획은 수량이 바뀌지 않는다 (이미 발주번호가 붙어 나갔다)
  - 입고완료 건은 입고예정에 넣지 않는다 (현재고에 이미 반영됨)
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.auth import Role
from app.models.enums import InboundStatus, MetricSource, PlanStatus, WarehouseType
from app.models.metrics import WeeklyMetric
from app.models.scm import Inbound, InventorySnapshot, MonthlyOrderPlan
from app.services import planning
from tests.conftest import sign_in
from tests.factories import make_brand, make_channel, make_product, make_warehouse

MONDAY = date(2026, 6, 15)


@pytest.fixture
def world(db: Session):
    brand = make_brand(db)
    hub = make_warehouse(db, name="용인 메인", type_=WarehouseType.HUB)
    ffc = make_warehouse(db, name="온라인 FFC", type_=WarehouseType.ONLINE)
    product = make_product(db, brand, product_code="H12", name="H12 Pro", pack_qty_per_tu=10)
    make_channel(db, name="쿠팡", warehouse=ffc)

    db.add(
        InventorySnapshot(
            snapshot_date=MONDAY, warehouse_id=ffc.id, product_id=product.id, qty=200
        )
    )
    from app.core.dates import iso_week_of

    for offset in range(1, 5):
        week = iso_week_of(MONDAY - timedelta(weeks=offset))
        db.add(
            WeeklyMetric(
                iso_year=week.year,
                iso_week=week.week,
                product_id=product.id,
                warehouse_id=ffc.id,
                outflow_qty=50,
                sales_qty=50,
                source=MetricSource.DERIVED,
            )
        )
    db.commit()
    return {"brand": brand, "hub": hub, "ffc": ffc, "product": product}


class TestOrderPlanSimulation:
    def test_arrival_month_is_six_months_after_the_order_month(
        self, db: Session, world: dict
    ) -> None:
        """리드타임을 고려해 6개월 뒤 도착분을 주문한다."""
        simulation = planning.simulate_order_plan(db, as_of=MONDAY)
        assert simulation.target_month == "2026-06"
        assert simulation.arrival_month == "2026-12"

    def test_demand_breakdown_is_exposed(self, db: Session, world: dict) -> None:
        """예측 근거가 항상 드러나야 한다 — 실무자가 손으로 따라갈 수 있게."""
        plan = planning.simulate_order_plan(db, as_of=MONDAY).plans[0]
        assert plan.smoothing_constant == pytest.approx(50.0)
        assert plan.loss_buffer == pytest.approx(0.0)
        assert plan.weekly_demand == pytest.approx(50.0)
        assert plan.current_stock == 200

    def test_suggestion_is_rounded_to_the_carton_unit(
        self, db: Session, world: dict
    ) -> None:
        """발주는 카툰 단위로 나간다. 낱개 수량을 그대로 주문할 수 없다."""
        plan = planning.simulate_order_plan(db, as_of=MONDAY).plans[0]
        assert plan.order_unit == 10
        assert plan.suggested_qty % 10 == 0

    def test_scheduled_inbound_lands_in_the_right_week(
        self, db: Session, world: dict
    ) -> None:
        db.add(
            Inbound(
                product_id=world["product"].id,
                arrival_warehouse_id=world["ffc"].id,
                eta=MONDAY + timedelta(weeks=3),
                unit_qty=500,
                status=InboundStatus.IN_TRANSIT,
            )
        )
        db.commit()

        plan = planning.simulate_order_plan(db, as_of=MONDAY).plans[0]
        assert plan.scheduled_inbounds == {4: 500}

    def test_received_inbound_is_not_counted_again(
        self, db: Session, world: dict
    ) -> None:
        """입고완료 수량은 현재고에 이미 들어 있다. 두 번 세면 과대평가다."""
        db.add(
            Inbound(
                product_id=world["product"].id,
                arrival_warehouse_id=world["ffc"].id,
                eta=MONDAY + timedelta(weeks=3),
                unit_qty=500,
                status=InboundStatus.RECEIVED,
            )
        )
        db.commit()

        plan = planning.simulate_order_plan(db, as_of=MONDAY).plans[0]
        assert plan.scheduled_inbounds == {}

    def test_inbound_beyond_the_horizon_is_ignored(
        self, db: Session, world: dict
    ) -> None:
        db.add(
            Inbound(
                product_id=world["product"].id,
                eta=MONDAY + timedelta(weeks=60),
                unit_qty=500,
                status=InboundStatus.IN_TRANSIT,
            )
        )
        db.commit()
        assert planning.simulate_order_plan(db, as_of=MONDAY).plans[0].scheduled_inbounds == {}

    def test_weight_factor_scales_demand_but_not_the_loss_buffer(
        self, db: Session, world: dict
    ) -> None:
        """감모는 판매량과 무관하게 발생하는 고정 손실로 본다."""
        base = planning.simulate_order_plan(db, as_of=MONDAY).plans[0]
        doubled = planning.simulate_order_plan(
            db, as_of=MONDAY, weight_factor=2.0
        ).plans[0]
        assert doubled.weekly_demand == pytest.approx(base.smoothing_constant * 2)


class TestSavePlans:
    def test_save_then_update(self, db: Session, world: dict) -> None:
        created, updated = planning.save_plans(db, "2026-06", {world["product"].id: 100})
        assert (created, updated) == (1, 0)

        created, updated = planning.save_plans(db, "2026-06", {world["product"].id: 250})
        assert (created, updated) == (0, 1)

        plan = db.query(MonthlyOrderPlan).one()
        assert plan.user_modified_qty == 250
        assert plan.version == 2

    def test_confirmed_plan_is_not_overwritten(self, db: Session, world: dict) -> None:
        """이미 발주번호가 붙어 나간 주문이다. 재시뮬레이션이 덮으면 안 된다."""
        planning.save_plans(db, "2026-06", {world["product"].id: 100})
        plan = db.query(MonthlyOrderPlan).one()
        plan.status = PlanStatus.CONFIRMED
        plan.purchase_code = "PC-2026-06-H12"
        db.commit()

        created, updated = planning.save_plans(db, "2026-06", {world["product"].id: 999})
        assert (created, updated) == (0, 0)

        db.refresh(plan)
        assert plan.user_modified_qty == 100


class TestInboundApi:
    def test_reads_require_login(self, client: TestClient) -> None:
        assert client.get("/api/inbound").status_code == 401

    def test_viewer_cannot_create(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.VIEWER)
        res = client.post(
            "/api/inbound",
            json={"product_id": world["product"].id, "unit_qty": 100},
            headers=headers,
        )
        assert res.status_code == 403

    def test_operator_can_create_and_response_has_status_order(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        res = client.post(
            "/api/inbound",
            json={
                "product_id": world["product"].id,
                "invoice_no": "INV-1",
                "unit_qty": 100,
                "status": "해상운송중",
            },
            headers=headers,
        )
        assert res.status_code == 201
        body = res.json()
        assert body["product_code"] == "H12"
        # 진행 단계 순번 — 생산국출발(0) 다음이 해상운송중(1)
        assert body["status_order"] == 1

    def test_unknown_product_is_404(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        res = client.post(
            "/api/inbound", json={"product_id": 9999, "unit_qty": 1}, headers=headers
        )
        assert res.status_code == 404

    def test_pending_filter_excludes_received(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        for status_value in (InboundStatus.IN_TRANSIT, InboundStatus.RECEIVED):
            db.add(
                Inbound(
                    product_id=world["product"].id,
                    unit_qty=10,
                    status=status_value,
                )
            )
        db.commit()
        sign_in(client, db, Role.VIEWER)

        assert len(client.get("/api/inbound").json()) == 2
        assert len(client.get("/api/inbound?pending_only=true").json()) == 1

    def test_invalid_status_is_rejected(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        res = client.post(
            "/api/inbound",
            json={"product_id": world["product"].id, "unit_qty": 1, "status": "우주여행중"},
            headers=headers,
        )
        assert res.status_code == 422


class TestOrderPlanApi:
    def test_simulation_endpoint_reports_both_months(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        sign_in(client, db, Role.VIEWER)
        body = client.get(f"/api/order-plan/simulation?as_of={MONDAY}").json()
        assert body["target_month"] == "2026-06"
        assert body["arrival_month"] == "2026-12"
        assert body["horizon_weeks"] == 24

    def test_save_requires_operator(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.VIEWER)
        res = client.post(
            "/api/order-plan",
            json={"target_month": "2026-06", "quantities": {world["product"].id: 100}},
            headers=headers,
        )
        assert res.status_code == 403

    def test_save_rejects_a_malformed_month(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        res = client.post(
            "/api/order-plan",
            json={"target_month": "2026년 6월", "quantities": {}},
            headers=headers,
        )
        assert res.status_code == 422

    def test_save_rejects_unknown_products(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        res = client.post(
            "/api/order-plan",
            json={"target_month": "2026-06", "quantities": {9999: 100}},
            headers=headers,
        )
        assert res.status_code == 404

    def test_optimistic_lock_rejects_a_stale_write(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        """다른 사람이 먼저 고쳤으면 덮어쓰지 않는다."""
        planning.save_plans(db, "2026-06", {world["product"].id: 100})
        plan = db.query(MonthlyOrderPlan).one()
        headers = sign_in(client, db, Role.OPERATOR)

        stale = client.put(
            f"/api/order-plan/{plan.id}",
            json={"user_modified_qty": 500, "version": plan.version - 1},
            headers=headers,
        )
        assert stale.status_code == 409

        fresh = client.put(
            f"/api/order-plan/{plan.id}",
            json={"user_modified_qty": 500, "version": plan.version},
            headers=headers,
        )
        assert fresh.status_code == 200
        assert fresh.json()["user_modified_qty"] == 500

    def test_confirmed_plan_quantity_cannot_be_changed(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        planning.save_plans(db, "2026-06", {world["product"].id: 100})
        plan = db.query(MonthlyOrderPlan).one()
        plan.status = PlanStatus.CONFIRMED
        db.commit()
        headers = sign_in(client, db, Role.OPERATOR)

        res = client.put(
            f"/api/order-plan/{plan.id}",
            json={"user_modified_qty": 999},
            headers=headers,
        )
        assert res.status_code == 409

    def test_confirmed_plan_cannot_be_deleted(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        planning.save_plans(db, "2026-06", {world["product"].id: 100})
        plan = db.query(MonthlyOrderPlan).one()
        plan.status = PlanStatus.CONFIRMED
        db.commit()
        headers = sign_in(client, db, Role.OPERATOR)

        res = client.delete(f"/api/order-plan/{plan.id}", headers=headers)
        assert res.status_code == 409

    def test_draft_plan_can_be_deleted(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        planning.save_plans(db, "2026-06", {world["product"].id: 100})
        plan = db.query(MonthlyOrderPlan).one()
        headers = sign_in(client, db, Role.OPERATOR)

        assert client.delete(f"/api/order-plan/{plan.id}", headers=headers).status_code == 200
        assert db.query(MonthlyOrderPlan).count() == 0
