"""
판매 · 분석 · 엑셀 API 테스트.

여기서 고정하는 것:
  - 원장을 바꾸면 그 주차 집계가 따라 바뀐다 (동기화 작업이 없다)
  - 미매핑 건도 저장되고, 별칭을 등록하면 재업로드 없이 해석된다
  - 대시보드 응답에 HTML 이 섞이지 않는다
  - 업로드는 행 단위로 실패하고 위치를 알려준다
"""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.models.auth import Role
from app.models.metrics import WeeklyMetric
from app.services import excel
from tests.conftest import sign_in
from tests.factories import (
    make_alias,
    make_brand,
    make_channel,
    make_product,
    make_sales_order,
    make_warehouse,
)

MONDAY = date(2026, 6, 15)


@pytest.fixture
def world(db: Session):
    brand = make_brand(db)
    warehouse = make_warehouse(db, name="온라인 FFC")
    channel = make_channel(db, name="쿠팡", channel_group="온라인", warehouse=warehouse)
    product = make_product(db, brand, product_code="H12", name="H12 Pro")
    make_alias(db, product, "드리미 H12 Pro", "H12 시리즈")
    return {
        "brand": brand,
        "warehouse": warehouse,
        "channel": channel,
        "product": product,
    }


def sheet(kind: excel.Kind, rows: list[list]) -> bytes:
    template = excel.TEMPLATES[kind]
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = template.sheet_name
    worksheet.append(template.headers)
    for row in rows:
        worksheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class TestSalesOrders:
    def test_reads_require_login(self, client: TestClient) -> None:
        assert client.get("/api/sales/orders").status_code == 401

    def test_creating_an_order_rebuilds_that_week(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        """원장이 진실이고 집계는 파생이다. 동기화 작업이 따로 없다."""
        headers = sign_in(client, db, Role.OPERATOR)
        res = client.post(
            "/api/sales/orders",
            json={
                "brand_id": world["brand"].id,
                "source_product_name": "드리미 H12 Pro",
                "source_channel_name": "쿠팡",
                "ship_date": "2026-06-19",
                "qty": 7,
                "amount": "70000",
            },
            headers=headers,
        )
        assert res.status_code == 201
        assert res.json()["is_mapped"] is True
        assert res.json()["iso_week"] == 25

        metric = db.query(WeeklyMetric).one()
        assert metric.sales_qty == 7

    def test_amount_is_derived_from_unit_price_when_missing(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        body = client.post(
            "/api/sales/orders",
            json={
                "brand_id": world["brand"].id,
                "source_product_name": "드리미 H12 Pro",
                "source_channel_name": "쿠팡",
                "ship_date": "2026-06-19",
                "qty": 3,
                "unit_price": "1000.50",
            },
            headers=headers,
        ).json()
        assert body["amount"] == "3001.50"

    def test_deleting_an_order_updates_the_aggregate(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        order = make_sales_order(
            db, world["brand"], ship_date=MONDAY, qty=10,
            product=world["product"], channel=world["channel"],
        )
        headers = sign_in(client, db, Role.OPERATOR)
        client.post("/api/sales/resolve", headers=headers)
        assert db.query(WeeklyMetric).count() == 1

        client.delete(f"/api/sales/orders/{order.id}", headers=headers)
        assert db.query(WeeklyMetric).count() == 0

    def test_zero_quantity_is_rejected(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        res = client.post(
            "/api/sales/orders",
            json={
                "brand_id": world["brand"].id,
                "source_product_name": "드리미 H12 Pro",
                "source_channel_name": "쿠팡",
                "ship_date": "2026-06-19",
                "qty": 0,
            },
            headers=headers,
        )
        assert res.status_code == 422


class TestMappingRecovery:
    def test_unmapped_names_are_stored_and_listed(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        client.post(
            "/api/sales/orders",
            json={
                "brand_id": world["brand"].id,
                "source_product_name": "낯선 제품",
                "source_channel_name": "쿠팡",
                "ship_date": "2026-06-19",
                "qty": 5,
            },
            headers=headers,
        )

        body = client.get("/api/sales/unmapped").json()
        assert body["products"] == ["낯선 제품"]
        assert body["channels"] == []

    def test_adding_an_alias_then_resolving_recovers_the_row(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        """원본 문자열을 보존해 두었으므로 재업로드가 필요 없다."""
        headers = sign_in(client, db, Role.ADMIN)
        client.post(
            "/api/sales/orders",
            json={
                "brand_id": world["brand"].id,
                "source_product_name": "낯선 제품",
                "source_channel_name": "쿠팡",
                "ship_date": "2026-06-19",
                "qty": 5,
            },
            headers=headers,
        )
        assert db.query(WeeklyMetric).count() == 0

        client.post(
            "/api/master/aliases",
            json={"source_name": "낯선 제품", "product_id": world["product"].id},
            headers=headers,
        )
        resolved = client.post("/api/sales/resolve", headers=headers).json()

        assert resolved["updated"] == 1
        assert resolved["remaining"]["products"] == []
        assert db.query(WeeklyMetric).one().sales_qty == 5

    def test_resolve_requires_operator(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.VIEWER)
        assert client.post("/api/sales/resolve", headers=headers).status_code == 403


class TestPromotions:
    def test_reversed_dates_are_rejected(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        res = client.post(
            "/api/sales/promotions",
            json={
                "brand_id": world["brand"].id,
                "start_date": "2026-06-21",
                "end_date": "2026-06-15",
                "source_channel_name": "쿠팡",
                "event_name": "여름 특가",
            },
            headers=headers,
        )
        assert res.status_code == 400

    def test_promotion_resolves_its_mappings(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        body = client.post(
            "/api/sales/promotions",
            json={
                "brand_id": world["brand"].id,
                "start_date": "2026-06-15",
                "end_date": "2026-06-21",
                "source_channel_name": "쿠팡",
                "source_product_name": "드리미 H12 Pro",
                "event_name": "여름 특가",
            },
            headers=headers,
        ).json()
        assert body["product_id"] == world["product"].id
        assert body["channel_id"] == world["channel"].id

    def test_active_on_filter(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        client.post(
            "/api/sales/promotions",
            json={
                "brand_id": world["brand"].id,
                "start_date": "2026-06-15",
                "end_date": "2026-06-21",
                "source_channel_name": "쿠팡",
                "event_name": "여름 특가",
            },
            headers=headers,
        )
        assert len(client.get("/api/sales/promotions?active_on=2026-06-18").json()) == 1
        assert len(client.get("/api/sales/promotions?active_on=2026-07-01").json()) == 0


class TestAnalyticsDashboard:
    def test_requires_login(self, client: TestClient) -> None:
        assert client.get("/api/analytics/dashboard").status_code == 401

    def test_dashboard_returns_a_full_screen(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        for day, qty in ((MONDAY, 30), (MONDAY - __import__("datetime").timedelta(days=7), 20)):
            make_sales_order(
                db, world["brand"], ship_date=day, qty=qty, amount="10000",
                product=world["product"], channel=world["channel"],
            )
        sign_in(client, db, Role.VIEWER)

        body = client.get("/api/analytics/dashboard?anchor=week:2026-W25").json()
        assert body["kpi"]["week_label"] == "Jun-W3"
        assert body["kpi"]["week"]["current"]["qty"] == 30
        assert body["kpi"]["week"]["qty_pct"] == 50.0
        assert body["channel_mix"][0]["channel_group"] == "온라인"
        assert body["meta"]["week_key"] == "2026-W25"

    def test_response_carries_no_markup(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        """구 버전은 알림 문구에 <strong> 을 박아 보냈다."""
        import datetime

        make_sales_order(
            db, world["brand"], ship_date=MONDAY - datetime.timedelta(days=7),
            qty=10, product=world["product"], channel=world["channel"],
        )
        make_sales_order(
            db, world["brand"], ship_date=MONDAY, qty=30,
            product=world["product"], channel=world["channel"],
        )
        sign_in(client, db, Role.VIEWER)

        text = client.get("/api/analytics/dashboard?anchor=week:2026-W25").text
        assert "<strong>" not in text
        assert "<" not in text.replace("\\u", "")

    def test_bad_anchor_falls_back_instead_of_failing(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        """조회 화면이 잘못된 입력 하나로 통째로 깨지면 안 된다."""
        sign_in(client, db, Role.VIEWER)
        res = client.get("/api/analytics/dashboard?anchor=쓰레기값")
        assert res.status_code == 200
        assert res.json()["meta"]["anchor"] == ""

    def test_empty_ledger_still_renders(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        sign_in(client, db, Role.VIEWER)
        body = client.get("/api/analytics/dashboard").json()
        assert body["kpi"]["week"]["current"]["qty"] == 0
        assert body["channel_mix"] == []
        assert body["alerts"] == []


class TestExcelApi:
    def test_template_list_covers_every_kind(
        self, client: TestClient, db: Session
    ) -> None:
        sign_in(client, db, Role.VIEWER)
        body = client.get("/api/excel/templates").json()
        assert {item["kind"] for item in body} == {kind.value for kind in excel.Kind}

    def test_template_download_has_a_korean_filename(
        self, client: TestClient, db: Session
    ) -> None:
        """한글 파일명을 그대로 헤더에 넣으면 깨진다. RFC 5987 로 인코딩한다."""
        sign_in(client, db, Role.VIEWER)
        res = client.get("/api/excel/templates/sales_order")
        assert res.status_code == 200
        assert "filename*=UTF-8''" in res.headers["content-disposition"]
        assert res.headers["content-type"].startswith("application/vnd.openxml")

    def test_unknown_template_is_404(self, client: TestClient, db: Session) -> None:
        sign_in(client, db, Role.VIEWER)
        assert client.get("/api/excel/templates/없는양식").status_code == 404

    def test_sales_upload_imports_and_rebuilds(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        content = sheet(
            excel.Kind.SALES_ORDER,
            [["가전", "쿠팡", "드리미 H12 Pro", 5, "2026-06-19", None, "ORD-1", None, "50000"]],
        )

        res = client.post(
            f"/api/excel/uploads/sales_order?brand_id={world['brand'].id}",
            files={"file": ("sales.xlsx", content)},
            headers=headers,
        )
        assert res.status_code == 200
        body = res.json()
        assert body["created"] == 1
        assert body["errors"] == []
        assert body["weeks_rebuilt"] == 1
        assert db.query(WeeklyMetric).one().sales_qty == 5

    def test_bad_row_is_reported_with_its_position(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        content = sheet(
            excel.Kind.SALES_ORDER,
            [
                ["가전", "쿠팡", "드리미 H12 Pro", 5, "2026-06-19", None, None, None, "1000"],
                ["가전", "쿠팡", "불량행", "셋", "2026-06-19", None, None, None, "1000"],
            ],
        )
        body = client.post(
            f"/api/excel/uploads/sales_order?brand_id={world['brand'].id}",
            files={"file": ("sales.xlsx", content)},
            headers=headers,
        ).json()

        assert body["created"] == 1
        assert body["errors"][0]["row_no"] == 3
        assert body["errors"][0]["column"] == "수량"

    def test_unresolved_names_are_surfaced(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        content = sheet(
            excel.Kind.SALES_ORDER,
            [["가전", "낯선채널", "낯선제품", 5, "2026-06-19", None, None, None, "1000"]],
        )
        body = client.post(
            f"/api/excel/uploads/sales_order?brand_id={world['brand'].id}",
            files={"file": ("sales.xlsx", content)},
            headers=headers,
        ).json()
        assert body["unresolved"] == ["제품: 낯선제품", "채널: 낯선채널"]

    def test_sales_upload_needs_a_brand(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        res = client.post(
            "/api/excel/uploads/sales_order",
            files={"file": ("sales.xlsx", sheet(excel.Kind.SALES_ORDER, []))},
            headers=headers,
        )
        assert res.status_code == 400
        assert "brand_id" in res.json()["detail"]

    def test_master_upload_requires_admin(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        """기준 정보는 운영자가 올릴 수 없다."""
        headers = sign_in(client, db, Role.OPERATOR)
        content = sheet(excel.Kind.PRODUCT, [["X30", "X30 로봇", "드리미", 1, "USD", "700"]])

        res = client.post(
            "/api/excel/uploads/product",
            files={"file": ("product.xlsx", content)},
            headers=headers,
        )
        assert res.status_code == 403

    def test_admin_can_upload_master_data(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.ADMIN)
        content = sheet(excel.Kind.PRODUCT, [["X30", "X30 로봇", "드리미", 1, "USD", "700"]])

        body = client.post(
            "/api/excel/uploads/product",
            files={"file": ("product.xlsx", content)},
            headers=headers,
        ).json()
        assert body["created"] == 1

    def test_viewer_cannot_upload(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.VIEWER)
        res = client.post(
            f"/api/excel/uploads/sales_order?brand_id={world['brand'].id}",
            files={"file": ("s.xlsx", sheet(excel.Kind.SALES_ORDER, []))},
            headers=headers,
        )
        assert res.status_code == 403

    def test_empty_file_is_rejected(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        res = client.post(
            f"/api/excel/uploads/sales_order?brand_id={world['brand'].id}",
            files={"file": ("empty.xlsx", b"")},
            headers=headers,
        )
        assert res.status_code == 400

    def test_corrupt_file_gives_a_readable_error(
        self, client: TestClient, db: Session, world: dict
    ) -> None:
        headers = sign_in(client, db, Role.OPERATOR)
        res = client.post(
            f"/api/excel/uploads/sales_order?brand_id={world['brand'].id}",
            files={"file": ("bad.xlsx", b"not a workbook at all")},
            headers=headers,
        )
        assert res.status_code == 400
        assert "엑셀" in res.json()["detail"]
