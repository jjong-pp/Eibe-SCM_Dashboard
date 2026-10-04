"""판매 원장 · 행사 스키마."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class SalesOrderCreate(BaseModel):
    brand_id: int
    source_product_name: str = Field(min_length=1, max_length=255)
    source_channel_name: str = Field(min_length=1, max_length=128)
    ship_date: date
    qty: int = Field(gt=0)
    order_no: str | None = Field(default=None, max_length=128)
    category: str | None = Field(default=None, max_length=128)
    order_date: date | None = None
    unit_price: Decimal | None = Field(default=None, ge=0)
    amount: Decimal | None = Field(default=None, ge=0)


class SalesOrderResponse(ORMModel):
    id: int
    brand_id: int
    order_no: str | None
    source_product_name: str
    source_channel_name: str
    category: str | None
    product_id: int | None
    product_code: str | None = None
    channel_id: int | None
    order_date: date | None
    ship_date: date
    iso_year: int
    iso_week: int
    qty: int
    unit_price: Decimal | None
    amount: Decimal
    #: 품목·채널이 모두 해석된 건만 재고 집계에 들어간다
    is_mapped: bool = False


class UnmappedSourcesResponse(BaseModel):
    """집계에서 빠지고 있는 원본 값.

    조용히 사라지지 않게 화면에 드러내기 위한 것이다. 별칭이나 채널을
    등록한 뒤 `/api/sales/resolve` 를 부르면 재업로드 없이 해석된다.
    """

    products: list[str]
    channels: list[str]


class ResolveResponse(BaseModel):
    updated: int
    remaining: UnmappedSourcesResponse
    message: str


class PromotionCreate(BaseModel):
    brand_id: int
    start_date: date
    end_date: date
    source_channel_name: str = Field(min_length=1, max_length=128)
    event_name: str = Field(min_length=1, max_length=255)
    source_product_name: str | None = Field(default=None, max_length=255)
    slot_name: str | None = Field(default=None, max_length=255)
    list_price: Decimal | None = Field(default=None, ge=0)
    price: Decimal | None = Field(default=None, ge=0)
    discount_rate: Decimal | None = Field(default=None, ge=0)
    reward_points: Decimal | None = Field(default=None, ge=0)
    gift: str | None = Field(default=None, max_length=255)
    note: str | None = None
    is_marketing: bool = False
    is_confirmed: bool = False


class PromotionResponse(ORMModel):
    id: int
    brand_id: int
    start_date: date
    end_date: date
    source_product_name: str | None
    source_channel_name: str | None
    product_id: int | None
    channel_id: int | None
    slot_name: str | None
    event_name: str | None
    list_price: Decimal | None
    price: Decimal | None
    discount_rate: Decimal | None
    gift: str | None
    is_marketing: bool
    is_confirmed: bool
