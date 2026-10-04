"""
기준 정보 API 테스트.

가장 중요한 것은 **권한**이다. 구 버전은 조회성 GET 에 가드를 하나씩 붙이는
방식이었고 그 결과 계정 목록이 무인증으로 노출됐다. 여기서는 라우터 기본값이
가드이므로, 그 전제가 실제로 성립하는지를 엔드포인트마다 확인한다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.auth import Role
from app.models.master import Product
from tests.conftest import sign_in
from tests.factories import make_brand, make_product, make_warehouse

# (메서드, 경로) — 로그인 없이 접근하면 401 이어야 하는 것들
PROTECTED = [
    ("get", "/api/master/brands"),
    ("get", "/api/master/products"),
    ("get", "/api/master/warehouses"),
    ("get", "/api/master/channels"),
    ("get", "/api/master/aliases"),
    ("get", "/api/master/logistics-costs"),
    ("get", "/api/master/warehouse-moq"),
]


class TestAuthorization:
    @pytest.mark.parametrize(("method", "path"), PROTECTED)
    def test_anonymous_cannot_read(
        self, client: TestClient, method: str, path: str
    ) -> None:
        assert getattr(client, method)(path).status_code == 401

    def test_viewer_can_read(self, client: TestClient, db: Session) -> None:
        sign_in(client, db, Role.VIEWER)
        assert client.get("/api/master/brands").status_code == 200

    def test_viewer_cannot_write(self, client: TestClient, db: Session) -> None:
        headers = sign_in(client, db, Role.VIEWER)
        res = client.post(
            "/api/master/brands",
            json={"name": "새 브랜드", "slug": "new-brand"},
            headers=headers,
        )
        assert res.status_code == 403

    def test_operator_cannot_write_master_data(
        self, client: TestClient, db: Session
    ) -> None:
        """기준 정보 변경은 관리자만. 운영자는 업무 데이터까지다."""
        headers = sign_in(client, db, Role.OPERATOR)
        res = client.post(
            "/api/master/brands",
            json={"name": "새 브랜드", "slug": "new-brand"},
            headers=headers,
        )
        assert res.status_code == 403

    def test_write_without_csrf_header_is_blocked(
        self, client: TestClient, db: Session
    ) -> None:
        sign_in(client, db, Role.ADMIN)  # 헤더를 일부러 쓰지 않는다
        res = client.post(
            "/api/master/brands", json={"name": "새 브랜드", "slug": "new-brand"}
        )
        assert res.status_code == 403
        assert "CSRF" in res.json()["detail"]


class TestBrand:
    def test_create_and_list(self, client: TestClient, db: Session) -> None:
        headers = sign_in(client, db, Role.ADMIN)

        res = client.post(
            "/api/master/brands",
            json={"name": "드리미", "slug": "dreame", "category": "ELECTRONICS"},
            headers=headers,
        )
        assert res.status_code == 201
        assert res.json()["slug"] == "dreame"

        listed = client.get("/api/master/brands").json()
        assert [brand["name"] for brand in listed] == ["드리미"]

    def test_slug_must_be_url_safe(self, client: TestClient, db: Session) -> None:
        headers = sign_in(client, db, Role.ADMIN)
        res = client.post(
            "/api/master/brands",
            json={"name": "드리미", "slug": "드리미"},
            headers=headers,
        )
        assert res.status_code == 422

    def test_duplicate_slug_is_a_conflict(
        self, client: TestClient, db: Session
    ) -> None:
        headers = sign_in(client, db, Role.ADMIN)
        payload = {"name": "드리미", "slug": "dreame"}
        assert client.post("/api/master/brands", json=payload, headers=headers).status_code == 201

        duplicate = client.post(
            "/api/master/brands",
            json={"name": "다른이름", "slug": "dreame"},
            headers=headers,
        )
        assert duplicate.status_code == 409

    def test_inactive_brands_are_hidden_unless_asked(
        self, client: TestClient, db: Session
    ) -> None:
        brand = make_brand(db)
        headers = sign_in(client, db, Role.ADMIN)

        client.put(
            f"/api/master/brands/{brand.id}", json={"is_active": False}, headers=headers
        )

        assert client.get("/api/master/brands").json() == []
        assert len(client.get("/api/master/brands?include_inactive=true").json()) == 1


class TestProduct:
    def test_response_carries_the_brand_name(
        self, client: TestClient, db: Session
    ) -> None:
        """화면이 별도로 브랜드 목록을 받아 조인하지 않아도 되게 한다."""
        brand = make_brand(db, name="드리미")
        make_product(db, brand, product_code="H12", name="H12 Pro")
        sign_in(client, db, Role.VIEWER)

        body = client.get("/api/master/products").json()
        assert body[0]["brand_name"] == "드리미"

    def test_create_rejects_an_unknown_brand(
        self, client: TestClient, db: Session
    ) -> None:
        headers = sign_in(client, db, Role.ADMIN)
        res = client.post(
            "/api/master/products",
            json={"product_code": "X1", "name": "미지품목", "brand_id": 9999},
            headers=headers,
        )
        assert res.status_code == 404
        assert "브랜드" in res.json()["detail"]

    def test_pack_qty_must_be_positive(self, client: TestClient, db: Session) -> None:
        brand = make_brand(db)
        headers = sign_in(client, db, Role.ADMIN)
        res = client.post(
            "/api/master/products",
            json={
                "product_code": "X1",
                "name": "품목",
                "brand_id": brand.id,
                "pack_qty_per_tu": 0,
            },
            headers=headers,
        )
        assert res.status_code == 422

    def test_update_leaves_omitted_fields_alone(
        self, client: TestClient, db: Session
    ) -> None:
        brand = make_brand(db)
        product = make_product(db, brand, product_code="H12", name="원래 이름")
        headers = sign_in(client, db, Role.ADMIN)

        client.put(
            f"/api/master/products/{product.id}",
            json={"name": "바뀐 이름"},
            headers=headers,
        )

        db.refresh(product)
        assert product.name == "바뀐 이름"
        assert product.pack_qty_per_tu == 24  # 건드리지 않았다

    def test_delete_deactivates_instead_of_removing(
        self, client: TestClient, db: Session
    ) -> None:
        """판매 이력과 재고 스냅샷이 참조한다. 과거 실적이 바뀌면 안 된다."""
        brand = make_brand(db)
        product = make_product(db, brand, product_code="H12")
        headers = sign_in(client, db, Role.ADMIN)

        res = client.delete(f"/api/master/products/{product.id}", headers=headers)
        assert res.status_code == 200

        db.expire_all()
        assert db.get(Product, product.id) is not None
        assert db.get(Product, product.id).is_active is False

    def test_missing_product_is_404(self, client: TestClient, db: Session) -> None:
        sign_in(client, db, Role.VIEWER)
        assert client.get("/api/master/products/9999").status_code == 404


class TestAlias:
    def test_alias_links_a_source_name_to_a_product(
        self, client: TestClient, db: Session
    ) -> None:
        brand = make_brand(db)
        product = make_product(db, brand, product_code="H12")
        headers = sign_in(client, db, Role.ADMIN)

        res = client.post(
            "/api/master/aliases",
            json={
                "source_name": "드리미 H12 Pro",
                "product_id": product.id,
                "lineup_name": "H12 시리즈",
            },
            headers=headers,
        )
        assert res.status_code == 201
        assert res.json()["product_code"] == "H12"

    def test_duplicate_source_name_is_a_conflict(
        self, client: TestClient, db: Session
    ) -> None:
        """한 원본 문자열이 두 품목을 가리키면 집계가 갈린다."""
        brand = make_brand(db)
        first = make_product(db, brand, product_code="H12")
        second = make_product(db, brand, product_code="L10")
        headers = sign_in(client, db, Role.ADMIN)

        client.post(
            "/api/master/aliases",
            json={"source_name": "드리미 H12", "product_id": first.id},
            headers=headers,
        )
        duplicate = client.post(
            "/api/master/aliases",
            json={"source_name": "드리미 H12", "product_id": second.id},
            headers=headers,
        )
        assert duplicate.status_code == 409

    def test_alias_is_really_deleted(self, client: TestClient, db: Session) -> None:
        """판매 원장이 원본 문자열을 들고 있어 잃는 것이 없다."""
        brand = make_brand(db)
        product = make_product(db, brand, product_code="H12")
        headers = sign_in(client, db, Role.ADMIN)

        created = client.post(
            "/api/master/aliases",
            json={"source_name": "드리미 H12", "product_id": product.id},
            headers=headers,
        ).json()

        client.delete(f"/api/master/aliases/{created['id']}", headers=headers)
        assert client.get("/api/master/aliases").json() == []


class TestChannel:
    def test_channel_response_carries_the_warehouse_name(
        self, client: TestClient, db: Session
    ) -> None:
        warehouse = make_warehouse(db, name="쿠팡 FFC")
        headers = sign_in(client, db, Role.ADMIN)

        res = client.post(
            "/api/master/channels",
            json={
                "name": "쿠팡",
                "channel_group": "온라인",
                "warehouse_id": warehouse.id,
                "is_major": True,
            },
            headers=headers,
        )
        assert res.status_code == 201
        assert res.json()["warehouse_name"] == "쿠팡 FFC"

    def test_unassigned_filter_finds_channels_missing_a_warehouse(
        self, client: TestClient, db: Session
    ) -> None:
        """창고가 없는 채널의 판매는 재고 집계에 들어가지 못한다. 찾아낼 수 있어야 한다."""
        warehouse = make_warehouse(db)
        headers = sign_in(client, db, Role.ADMIN)

        client.post(
            "/api/master/channels",
            json={"name": "쿠팡", "warehouse_id": warehouse.id},
            headers=headers,
        )
        client.post("/api/master/channels", json={"name": "떠리몰"}, headers=headers)

        unassigned = client.get("/api/master/channels?unassigned_only=true").json()
        assert [channel["name"] for channel in unassigned] == ["떠리몰"]

    def test_unknown_warehouse_is_rejected(
        self, client: TestClient, db: Session
    ) -> None:
        headers = sign_in(client, db, Role.ADMIN)
        res = client.post(
            "/api/master/channels",
            json={"name": "쿠팡", "warehouse_id": 9999},
            headers=headers,
        )
        assert res.status_code == 404


class TestLogisticsCost:
    def test_same_endpoints_are_rejected(
        self, client: TestClient, db: Session
    ) -> None:
        warehouse = make_warehouse(db)
        headers = sign_in(client, db, Role.ADMIN)

        res = client.post(
            "/api/master/logistics-costs",
            json={
                "departure_warehouse_id": warehouse.id,
                "arrival_warehouse_id": warehouse.id,
                "cost_per_tu": "1000",
            },
            headers=headers,
        )
        assert res.status_code == 400

    def test_posting_the_same_route_twice_updates_it(
        self, client: TestClient, db: Session
    ) -> None:
        """구간 하나에 비용 하나. 두 값이 있으면 어느 쪽이 맞는지 알 수 없다."""
        hub = make_warehouse(db, name="용인 메인")
        ffc = make_warehouse(db, name="온라인 FFC")
        headers = sign_in(client, db, Role.ADMIN)

        payload = {
            "departure_warehouse_id": hub.id,
            "arrival_warehouse_id": ffc.id,
            "cost_per_tu": "1000",
        }
        client.post("/api/master/logistics-costs", json=payload, headers=headers)
        client.post(
            "/api/master/logistics-costs", json={**payload, "cost_per_tu": "1500"},
            headers=headers,
        )

        costs = client.get("/api/master/logistics-costs").json()
        assert len(costs) == 1
        assert costs[0]["cost_per_tu"] == "1500.00"
        assert costs[0]["departure_warehouse_name"] == "용인 메인"


class TestWarehouseMoq:
    def test_moq_exception_is_upserted(self, client: TestClient, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand, product_code="H12")
        warehouse = make_warehouse(db)
        headers = sign_in(client, db, Role.ADMIN)

        payload = {
            "warehouse_id": warehouse.id,
            "product_id": product.id,
            "transfer_moq": 100,
        }
        client.post("/api/master/warehouse-moq", json=payload, headers=headers)
        res = client.post(
            "/api/master/warehouse-moq", json={**payload, "transfer_moq": 250},
            headers=headers,
        )

        assert res.json()["transfer_moq"] == 250
        assert res.json()["product_code"] == "H12"
        assert len(client.get("/api/master/warehouse-moq").json()) == 1

    def test_negative_moq_is_rejected(self, client: TestClient, db: Session) -> None:
        brand = make_brand(db)
        product = make_product(db, brand)
        warehouse = make_warehouse(db)
        headers = sign_in(client, db, Role.ADMIN)

        res = client.post(
            "/api/master/warehouse-moq",
            json={
                "warehouse_id": warehouse.id,
                "product_id": product.id,
                "transfer_moq": -1,
            },
            headers=headers,
        )
        assert res.status_code == 422
