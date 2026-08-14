"""
기준 정보 스키마.

응답에는 **화면이 쓰는 이름을 함께 담는다.** 구 버전은 `warehouse_id` 만
돌려주고 프론트가 별도로 창고 목록을 받아 조인했는데, 목록이 갱신되기 전에는
빈칸이 뜨거나 엉뚱한 이름이 붙었다. 서버가 한 번에 붙여 보내면 그 틈이 없다.

수량·금액 하한은 DB CHECK 제약과 같은 값으로 둔다. 여기서 먼저 걸러야
400 을 돌려줄 수 있고, 통과하더라도 DB 가 마지막 방어선으로 남는다.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import BrandCategory, WarehouseType
from app.schemas.common import ORMModel

# 통화 코드는 ISO 4217 3글자.
_CURRENCY = Field(default="USD", min_length=3, max_length=8)


# ══════════════════════════════════════════════════════════════════════
# 브랜드
# ══════════════════════════════════════════════════════════════════════


class BrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    category: BrandCategory = BrandCategory.FOOD

    @field_validator("name", "slug")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class BrandUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    category: BrandCategory | None = None
    is_active: bool | None = None


class BrandResponse(ORMModel):
    id: int
    name: str
    slug: str
    category: BrandCategory
    is_active: bool

    @property
    def expiry_label(self) -> str:
        """화면에서 쓰는 기한 표기. 전자제품은 '보증기한'이다."""
        return "보증기한" if self.category is BrandCategory.ELECTRONICS else "유통기한"


# ══════════════════════════════════════════════════════════════════════
# 품목
# ══════════════════════════════════════════════════════════════════════


class ProductCreate(BaseModel):
    product_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    brand_id: int
    pack_qty_per_tu: int = Field(default=24, gt=0)
    currency: str = _CURRENCY
    purchase_price: Decimal = Field(default=Decimal("0"), ge=0)

    @field_validator("product_code", "name")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class ProductUpdate(BaseModel):
    """품목코드는 업무상 식별자라 바꾸지 않는다 (구 문서 규칙)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    brand_id: int | None = None
    pack_qty_per_tu: int | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    purchase_price: Decimal | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ProductResponse(ORMModel):
    id: int
    product_code: str
    name: str
    brand_id: int
    brand_name: str | None = None
    pack_qty_per_tu: int
    currency: str
    purchase_price: Decimal
    is_active: bool


# ══════════════════════════════════════════════════════════════════════
# 제품 별칭 (판매 원장 ↔ 품목 접합점)
# ══════════════════════════════════════════════════════════════════════


class ProductAliasCreate(BaseModel):
    source_name: str = Field(min_length=1, max_length=255)
    product_id: int
    lineup_name: str | None = Field(default=None, max_length=255)

    @field_validator("source_name")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class ProductAliasResponse(ORMModel):
    id: int
    source_name: str
    product_id: int
    product_code: str | None = None
    lineup_name: str | None


# ══════════════════════════════════════════════════════════════════════
# 창고
# ══════════════════════════════════════════════════════════════════════


class WarehouseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    type: WarehouseType = WarehouseType.ONLINE
    allowed_expiry_days: int = Field(default=90, ge=0)
    default_transfer_moq: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class WarehouseUpdate(BaseModel):
    type: WarehouseType | None = None
    allowed_expiry_days: int | None = Field(default=None, ge=0)
    default_transfer_moq: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class WarehouseResponse(ORMModel):
    id: int
    name: str
    type: WarehouseType
    allowed_expiry_days: int
    default_transfer_moq: int
    is_active: bool


# ══════════════════════════════════════════════════════════════════════
# 채널 (판매 ↔ 창고 접합점)
# ══════════════════════════════════════════════════════════════════════


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    channel_group: str | None = Field(default=None, max_length=128)
    warehouse_id: int | None = None
    is_major: bool = False

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class ChannelUpdate(BaseModel):
    channel_group: str | None = Field(default=None, max_length=128)
    warehouse_id: int | None = None
    is_major: bool | None = None
    is_active: bool | None = None


class ChannelResponse(ORMModel):
    id: int
    name: str
    channel_group: str | None
    warehouse_id: int | None
    warehouse_name: str | None = None
    is_major: bool
    is_active: bool


# ══════════════════════════════════════════════════════════════════════
# 물류비 · 이관 MOQ
# ══════════════════════════════════════════════════════════════════════


class LogisticsCostCreate(BaseModel):
    departure_warehouse_id: int
    arrival_warehouse_id: int
    cost_per_tu: Decimal = Field(default=Decimal("0"), ge=0)


class LogisticsCostResponse(ORMModel):
    id: int
    departure_warehouse_id: int
    departure_warehouse_name: str | None = None
    arrival_warehouse_id: int
    arrival_warehouse_name: str | None = None
    cost_per_tu: Decimal


class WarehouseMoqCreate(BaseModel):
    warehouse_id: int
    product_id: int
    transfer_moq: int = Field(default=0, ge=0)


class WarehouseMoqResponse(ORMModel):
    id: int
    warehouse_id: int
    warehouse_name: str | None = None
    product_id: int
    product_code: str | None = None
    transfer_moq: int
