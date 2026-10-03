"""전 페이지·조회 API 스모크 테스트. 라우트가 추가되면 목록에 함께 추가한다."""

import pytest

PAGES = [
    "/",
    "/login",
    "/inventory",
    "/inventory/transfer",
    "/expiry",
    "/order-plan",
    "/matching",
    "/users",
]

GET_APIS = [
    "/api/health",
    "/api/auth/me",
    "/api/products",
    "/api/warehouses",
    "/api/logistics-cost",
    "/api/warehouse-moq",
    "/api/inventory-snapshot",
    "/api/inventory/summary",
    "/api/expiry/summary",
    "/api/order-plan",
    "/api/order-plan/simulation",
    "/api/outflow",
    "/api/sales",
    "/api/excel/template-types",
    "/api/orders",
    "/api/productions",
    "/api/inbound",
    "/api/snapshot/list",
    "/api/users",
]


@pytest.mark.parametrize("path", PAGES)
def test_page_serves_html(client, path):
    res = client.get(path)
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


@pytest.mark.parametrize("path", GET_APIS)
def test_get_api_ok(client, auth_headers, path):
    res = client.get(path, headers=auth_headers)
    assert res.status_code == 200, f"{path} -> {res.status_code}: {res.text[:300]}"


def test_login_rejects_wrong_password(client):
    res = client.post("/api/auth/login", data={"username": "admin", "password": "wrong"})
    assert res.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_seed_populates_products(client, auth_headers):
    products = client.get("/api/products", headers=auth_headers).json()
    assert len(products) > 0
