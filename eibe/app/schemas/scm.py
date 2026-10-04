"""
공급망 스키마 — 재고 · 입고 · 발주.

서비스가 돌려주는 dataclass 를 그대로 응답으로 쓰지 않고 여기서 한 겹 감싼다.
계약을 고정해 두어야 내부 계산 구조를 바꿔도 화면이 깨지지 않는다.

`math.inf` 는 JSON 이 표현하지 못한다 (`Infinity` 는 표준이 아니고 파서마다
다르게 처리한다). 재고일수가 무한대인 경우는 **`null` 로 내보내고** 화면이
'소진 불가'로 표시한다.
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import InboundStatus, PlanStatus
from app.schemas.common import ORMModel


def nullable_weeks(value: float | None) -> float | None:
    """무한대를 None 으로. JSON 에 Infinity 를 실어보내지 않는다."""
    if value is None or math.isinf(value) or math.isnan(value):
        return None
    return round(value, 1)


# ══════════════════════════════════════════════════════════════════════
# 재고 스냅샷
# ══════════════════════════════════════════════════════════════════════


class SnapshotCreate(BaseModel):
    snapshot_date: date
    warehouse_id: int
    product_id: int
    expiry_date: date | None = None
    qty: int = Field(ge=0)


class SnapshotResponse(ORMModel):
    id: int
    snapshot_date: date
    warehouse_id: int
    warehouse_name: str | None = None
    product_id: int
    product_code: str | None = None
    expiry_date: date | None
    qty: int


# ══════════════════════════════════════════════════════════════════════
# 재고 현황 (히트맵)
# ══════════════════════════════════════════════════════════════════════


class StockPositionResponse(BaseModel):
    product_id: int
    product_code: str
    product_name: str
    warehouse_id: int | None
    warehouse_name: str | None
    qty: int
    snapshot_date: date | None
    weekly_demand: float
    smoothing_constant: float
    loss_buffer: float
    #: null = 소진 불가 (주간 수요가 0)
    weeks_of_supply: float | None
    #: CSS 클래스명과 같은 값이다 (risk-high / risk-mid / risk-low / risk-safe)
    risk: str
    expiry_label: str


class StockSummaryResponse(BaseModel):
    as_of: date
    #: 구간 경계 (주). 화면 범례가 이 값을 그대로 쓴다.
    thresholds_weeks: list[float]
    positions: list[StockPositionResponse]


# ══════════════════════════════════════════════════════════════════════
# 유통기한
# ══════════════════════════════════════════════════════════════════════


class ExpiryLotResponse(BaseModel):
    product_id: int
    product_code: str
    product_name: str
    warehouse_id: int
    warehouse_name: str
    expiry_date: date | None
    qty: int
    qty_ahead: int
    days_remaining: int | None
    weeks_to_clear: float | None
    is_at_risk: bool
    #: False 면 is_at_risk 는 '위험 없음'이 아니라 '판단 근거 없음'이다
    is_judgeable: bool
    expiry_label: str


class ExpiryReportResponse(BaseModel):
    as_of: date
    at_risk_count: int
    unjudged_count: int
    lots: list[ExpiryLotResponse]


# ══════════════════════════════════════════════════════════════════════
# 이관
# ══════════════════════════════════════════════════════════════════════


class TransferSuggestionResponse(BaseModel):
    product_id: int
    product_code: str
    product_name: str
    from_warehouse_id: int
    from_warehouse_name: str
    to_warehouse_id: int
    to_warehouse_name: str
    current_qty: int
    weekly_demand: float
    weeks_of_supply: float | None
    shortage_qty: int
    suggested_qty: int
    moq: int
    limited_by_hub: bool
    cost: Decimal | None


class TransferPlanResponse(BaseModel):
    as_of: date
    target_weeks: float
    total_qty: int
    suggestions: list[TransferSuggestionResponse]
    #: HUB 재고가 모자라 채우지 못한 (품목 → 창고)
    shortfalls: list[str]


# ══════════════════════════════════════════════════════════════════════
# 입고
# ══════════════════════════════════════════════════════════════════════


class InboundCreate(BaseModel):
    product_id: int
    invoice_no: str | None = Field(default=None, max_length=64)
    bl_no: str | None = Field(default=None, max_length=64)
    purchase_code: str | None = Field(default=None, max_length=64)
    production_code: str | None = Field(default=None, max_length=64)
    arrival_warehouse_id: int | None = None
    shipping_date: date | None = None
    korea_arrival_date: date | None = None
    eta: date | None = None
    manufacture_date: date | None = None
    expiry_date: date | None = None
    carton_qty: int | None = Field(default=None, ge=0)
    unit_qty: int = Field(default=0, ge=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    total_price: Decimal | None = Field(default=None, ge=0)
    exchange_rate: Decimal | None = Field(default=None, ge=0)
    payment_amount_krw: Decimal | None = Field(default=None, ge=0)
    invoice_date: date | None = None
    payment_date: date | None = None
    status: InboundStatus = InboundStatus.DEPARTED


class InboundUpdate(BaseModel):
    """진행 상태와 일정이 자주 바뀌므로 전 필드를 선택적으로 둔다."""

    invoice_no: str | None = Field(default=None, max_length=64)
    bl_no: str | None = Field(default=None, max_length=64)
    purchase_code: str | None = Field(default=None, max_length=64)
    production_code: str | None = Field(default=None, max_length=64)
    arrival_warehouse_id: int | None = None
    shipping_date: date | None = None
    korea_arrival_date: date | None = None
    eta: date | None = None
    manufacture_date: date | None = None
    expiry_date: date | None = None
    carton_qty: int | None = Field(default=None, ge=0)
    unit_qty: int | None = Field(default=None, ge=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    total_price: Decimal | None = Field(default=None, ge=0)
    exchange_rate: Decimal | None = Field(default=None, ge=0)
    payment_amount_krw: Decimal | None = Field(default=None, ge=0)
    invoice_date: date | None = None
    payment_date: date | None = None
    status: InboundStatus | None = None


class InboundResponse(ORMModel):
    id: int
    invoice_no: str | None
    bl_no: str | None
    purchase_code: str | None
    production_code: str | None
    product_id: int
    product_code: str | None = None
    product_name: str | None = None
    arrival_warehouse_id: int | None
    arrival_warehouse_name: str | None = None
    shipping_date: date | None
    korea_arrival_date: date | None
    eta: date | None
    manufacture_date: date | None
    expiry_date: date | None
    carton_qty: int | None
    unit_qty: int
    unit_price: Decimal | None
    total_price: Decimal | None
    exchange_rate: Decimal | None
    payment_amount_krw: Decimal | None
    invoice_date: date | None
    payment_date: date | None
    status: InboundStatus
    #: 진행 단계 순번. 화면이 파이프라인 순서로 정렬할 때 쓴다.
    status_order: int = 0


# ══════════════════════════════════════════════════════════════════════
# 발주 계획
# ══════════════════════════════════════════════════════════════════════


class AirShipmentResponse(BaseModel):
    week: int
    shortage_qty: float
    message: str


class ProductPlanResponse(BaseModel):
    product_id: int
    product_code: str
    product_name: str
    current_stock: int
    smoothing_constant: float
    loss_buffer: float
    weekly_demand: float
    weeks_of_supply: float | None
    risk: str
    scheduled_inbounds: dict[int, int]
    suggested_qty: int
    order_unit: int
    final_stock: float
    first_stockout_week: int | None
    air_shipment: AirShipmentResponse | None
    target_month: str
    arrival_month: str


class OrderPlanSimulationResponse(BaseModel):
    target_month: str
    #: 리드타임을 고려한 도착월 — 발주월 + 6개월
    arrival_month: str
    horizon_weeks: int
    total_suggested_qty: int
    urgent_count: int
    plans: list[ProductPlanResponse]


class OrderPlanSaveRequest(BaseModel):
    target_month: str = Field(pattern=r"^\d{4}-\d{2}$")
    arrival_month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    #: {품목 id: 수량}
    quantities: dict[int, int]


class OrderPlanUpdate(BaseModel):
    user_modified_qty: int | None = Field(default=None, ge=0)
    note: str | None = None
    status: PlanStatus | None = None
    purchase_code: str | None = Field(default=None, max_length=64)
    #: 낙관적 잠금 — 읽어온 버전을 되돌려 보낸다. 다르면 409.
    version: int | None = None


class OrderPlanResponse(ORMModel):
    id: int
    target_month: str
    arrival_month: str | None
    product_id: int
    product_code: str | None = None
    product_name: str | None = None
    system_suggested_qty: int
    user_modified_qty: int
    status: PlanStatus
    purchase_code: str | None
    note: str | None
    version: int
