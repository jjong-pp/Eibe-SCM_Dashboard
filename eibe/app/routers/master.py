"""
기준 정보 API — 브랜드 · 품목 · 별칭 · 창고 · 채널 · 물류비 · 이관 MOQ.

권한: 조회는 로그인만, 변경은 관리자. 라우터 기본값이 `require_viewer` 이고
쓰기 라우트에만 `require_admin` 을 덧붙인다. FastAPI 는 두 의존성을 **합치므로**
관리자 가드가 빠지는 실수는 조회 권한으로 떨어질 뿐 무인증이 되지 않는다.

삭제 규칙 — **참조되는 기준 정보는 지우지 않고 비활성화한다.**
품목을 지우면 그 품목의 판매 이력과 재고 스냅샷이 참조를 잃는다. 과거 실적은
바뀌면 안 되는 사실이므로, `is_active=False` 로 목록에서만 뺀다. 참조가 없는
설정성 데이터(물류비 · 이관 MOQ)만 실제로 지운다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import require_admin, require_viewer
from app.database import get_db
from app.models.base import Base
from app.models.master import (
    Brand,
    Channel,
    LogisticsCost,
    Product,
    ProductAlias,
    Warehouse,
    WarehouseProductMoq,
)
from app.schemas.common import MessageResponse
from app.schemas.master import (
    BrandCreate,
    BrandResponse,
    BrandUpdate,
    ChannelCreate,
    ChannelResponse,
    ChannelUpdate,
    LogisticsCostCreate,
    LogisticsCostResponse,
    ProductAliasCreate,
    ProductAliasResponse,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    WarehouseCreate,
    WarehouseMoqCreate,
    WarehouseMoqResponse,
    WarehouseResponse,
    WarehouseUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/master",
    tags=["기준 정보"],
    dependencies=[Depends(require_viewer)],
)

_admin = Depends(require_admin)


def _get_or_404[T: Base](db: Session, model: type[T], pk: int, label: str) -> T:
    instance = db.get(model, pk)
    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{label} 정보를 찾을 수 없습니다.",
        )
    return instance


def _apply(instance: object, payload: object) -> None:
    """전달된 필드만 반영한다. 생략된 값은 건드리지 않는다."""
    for attribute, value in payload.model_dump(exclude_unset=True).items():
        setattr(instance, attribute, value)


# ══════════════════════════════════════════════════════════════════════
# 브랜드
# ══════════════════════════════════════════════════════════════════════


@router.get("/brands", response_model=list[BrandResponse])
def list_brands(
    include_inactive: bool = False, db: Session = Depends(get_db)
) -> list[Brand]:
    stmt = select(Brand).order_by(Brand.name)
    if not include_inactive:
        stmt = stmt.where(Brand.is_active.is_(True))
    return list(db.scalars(stmt))


@router.post(
    "/brands",
    response_model=BrandResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_admin],
)
def create_brand(payload: BrandCreate, db: Session = Depends(get_db)) -> Brand:
    brand = Brand(**payload.model_dump())
    db.add(brand)
    db.commit()
    db.refresh(brand)
    logger.info("브랜드 생성: %s", brand.slug)
    return brand


@router.put("/brands/{brand_id}", response_model=BrandResponse, dependencies=[_admin])
def update_brand(
    brand_id: int, payload: BrandUpdate, db: Session = Depends(get_db)
) -> Brand:
    brand = _get_or_404(db, Brand, brand_id, "브랜드")
    _apply(brand, payload)
    db.commit()
    db.refresh(brand)
    return brand


# ══════════════════════════════════════════════════════════════════════
# 품목
# ══════════════════════════════════════════════════════════════════════


def _product_response(product: Product) -> ProductResponse:
    response = ProductResponse.model_validate(product)
    return response.model_copy(
        update={"brand_name": product.brand.name if product.brand else None}
    )


@router.get("/products", response_model=list[ProductResponse])
def list_products(
    brand_id: int | None = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
) -> list[ProductResponse]:
    stmt = (
        select(Product)
        .options(selectinload(Product.brand))  # 브랜드명을 붙이므로 미리 읽는다
        .order_by(Product.product_code)
    )
    if brand_id is not None:
        stmt = stmt.where(Product.brand_id == brand_id)
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    return [_product_response(product) for product in db.scalars(stmt)]


@router.get("/products/{product_id}", response_model=ProductResponse)
def read_product(product_id: int, db: Session = Depends(get_db)) -> ProductResponse:
    return _product_response(_get_or_404(db, Product, product_id, "품목"))


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_admin],
)
def create_product(
    payload: ProductCreate, db: Session = Depends(get_db)
) -> ProductResponse:
    _get_or_404(db, Brand, payload.brand_id, "브랜드")
    product = Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    logger.info("품목 생성: %s", product.product_code)
    return _product_response(product)


@router.put(
    "/products/{product_id}", response_model=ProductResponse, dependencies=[_admin]
)
def update_product(
    product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)
) -> ProductResponse:
    product = _get_or_404(db, Product, product_id, "품목")
    if payload.brand_id is not None:
        _get_or_404(db, Brand, payload.brand_id, "브랜드")
    _apply(product, payload)
    db.commit()
    db.refresh(product)
    return _product_response(product)


@router.delete(
    "/products/{product_id}", response_model=MessageResponse, dependencies=[_admin]
)
def deactivate_product(
    product_id: int, db: Session = Depends(get_db)
) -> MessageResponse:
    """비활성화. 판매 이력과 재고 스냅샷이 참조하므로 실제로 지우지 않는다."""
    product = _get_or_404(db, Product, product_id, "품목")
    product.is_active = False
    db.commit()
    return MessageResponse(message=f"품목 {product.product_code} 을(를) 비활성화했습니다.")


# ══════════════════════════════════════════════════════════════════════
# 제품 별칭 — 판매 원장과 품목을 잇는 접합점
# ══════════════════════════════════════════════════════════════════════


def _alias_response(alias: ProductAlias) -> ProductAliasResponse:
    response = ProductAliasResponse.model_validate(alias)
    return response.model_copy(
        update={"product_code": alias.product.product_code if alias.product else None}
    )


@router.get("/aliases", response_model=list[ProductAliasResponse])
def list_aliases(
    product_id: int | None = None, db: Session = Depends(get_db)
) -> list[ProductAliasResponse]:
    stmt = (
        select(ProductAlias)
        .options(selectinload(ProductAlias.product))
        .order_by(ProductAlias.source_name)
    )
    if product_id is not None:
        stmt = stmt.where(ProductAlias.product_id == product_id)
    return [_alias_response(alias) for alias in db.scalars(stmt)]


@router.post(
    "/aliases",
    response_model=ProductAliasResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_admin],
)
def create_alias(
    payload: ProductAliasCreate, db: Session = Depends(get_db)
) -> ProductAliasResponse:
    """별칭 추가.

    이미 올라온 판매 건도 이 별칭으로 다시 해석된다. 재업로드가 필요 없도록
    원본 문자열을 보존해 두었기 때문이다 — 해석은 `/api/sales/resolve` 에서.
    """
    _get_or_404(db, Product, payload.product_id, "품목")
    alias = ProductAlias(**payload.model_dump())
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return _alias_response(alias)


@router.delete(
    "/aliases/{alias_id}", response_model=MessageResponse, dependencies=[_admin]
)
def delete_alias(alias_id: int, db: Session = Depends(get_db)) -> MessageResponse:
    """별칭은 실제로 지운다. 판매 원장은 원본 문자열을 들고 있어 잃는 것이 없다."""
    alias = _get_or_404(db, ProductAlias, alias_id, "별칭")
    source_name = alias.source_name
    db.delete(alias)
    db.commit()
    return MessageResponse(message=f"별칭 {source_name} 을(를) 삭제했습니다.")


# ══════════════════════════════════════════════════════════════════════
# 창고
# ══════════════════════════════════════════════════════════════════════


@router.get("/warehouses", response_model=list[WarehouseResponse])
def list_warehouses(
    include_inactive: bool = False, db: Session = Depends(get_db)
) -> list[Warehouse]:
    stmt = select(Warehouse).order_by(Warehouse.name)
    if not include_inactive:
        stmt = stmt.where(Warehouse.is_active.is_(True))
    return list(db.scalars(stmt))


@router.post(
    "/warehouses",
    response_model=WarehouseResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_admin],
)
def create_warehouse(
    payload: WarehouseCreate, db: Session = Depends(get_db)
) -> Warehouse:
    warehouse = Warehouse(**payload.model_dump())
    db.add(warehouse)
    db.commit()
    db.refresh(warehouse)
    return warehouse


@router.put(
    "/warehouses/{warehouse_id}",
    response_model=WarehouseResponse,
    dependencies=[_admin],
)
def update_warehouse(
    warehouse_id: int, payload: WarehouseUpdate, db: Session = Depends(get_db)
) -> Warehouse:
    warehouse = _get_or_404(db, Warehouse, warehouse_id, "창고")
    _apply(warehouse, payload)
    db.commit()
    db.refresh(warehouse)
    return warehouse


@router.delete(
    "/warehouses/{warehouse_id}",
    response_model=MessageResponse,
    dependencies=[_admin],
)
def deactivate_warehouse(
    warehouse_id: int, db: Session = Depends(get_db)
) -> MessageResponse:
    warehouse = _get_or_404(db, Warehouse, warehouse_id, "창고")
    warehouse.is_active = False
    db.commit()
    return MessageResponse(message=f"창고 {warehouse.name} 을(를) 비활성화했습니다.")


# ══════════════════════════════════════════════════════════════════════
# 채널 — 판매와 창고를 잇는 접합점
# ══════════════════════════════════════════════════════════════════════


def _channel_response(channel: Channel) -> ChannelResponse:
    response = ChannelResponse.model_validate(channel)
    return response.model_copy(
        update={"warehouse_name": channel.warehouse.name if channel.warehouse else None}
    )


@router.get("/channels", response_model=list[ChannelResponse])
def list_channels(
    include_inactive: bool = False,
    unassigned_only: bool = Query(
        False, description="창고가 연결되지 않은 채널만 — 집계에서 빠지는 것들"
    ),
    db: Session = Depends(get_db),
) -> list[ChannelResponse]:
    stmt = (
        select(Channel)
        .options(selectinload(Channel.warehouse))
        .order_by(Channel.name)
    )
    if not include_inactive:
        stmt = stmt.where(Channel.is_active.is_(True))
    if unassigned_only:
        stmt = stmt.where(Channel.warehouse_id.is_(None))
    return [_channel_response(channel) for channel in db.scalars(stmt)]


@router.post(
    "/channels",
    response_model=ChannelResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_admin],
)
def create_channel(
    payload: ChannelCreate, db: Session = Depends(get_db)
) -> ChannelResponse:
    if payload.warehouse_id is not None:
        _get_or_404(db, Warehouse, payload.warehouse_id, "창고")
    channel = Channel(**payload.model_dump())
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return _channel_response(channel)


@router.put(
    "/channels/{channel_id}", response_model=ChannelResponse, dependencies=[_admin]
)
def update_channel(
    channel_id: int, payload: ChannelUpdate, db: Session = Depends(get_db)
) -> ChannelResponse:
    channel = _get_or_404(db, Channel, channel_id, "채널")
    if payload.warehouse_id is not None:
        _get_or_404(db, Warehouse, payload.warehouse_id, "창고")
    _apply(channel, payload)
    db.commit()
    db.refresh(channel)
    return _channel_response(channel)


@router.delete(
    "/channels/{channel_id}", response_model=MessageResponse, dependencies=[_admin]
)
def deactivate_channel(
    channel_id: int, db: Session = Depends(get_db)
) -> MessageResponse:
    channel = _get_or_404(db, Channel, channel_id, "채널")
    channel.is_active = False
    db.commit()
    return MessageResponse(message=f"채널 {channel.name} 을(를) 비활성화했습니다.")


# ══════════════════════════════════════════════════════════════════════
# 물류비 — 구간별 카툰당 비용
# ══════════════════════════════════════════════════════════════════════


def _logistics_response(cost: LogisticsCost) -> LogisticsCostResponse:
    response = LogisticsCostResponse.model_validate(cost)
    return response.model_copy(
        update={
            "departure_warehouse_name": cost.departure_warehouse.name,
            "arrival_warehouse_name": cost.arrival_warehouse.name,
        }
    )


@router.get("/logistics-costs", response_model=list[LogisticsCostResponse])
def list_logistics_costs(db: Session = Depends(get_db)) -> list[LogisticsCostResponse]:
    costs = db.scalars(
        select(LogisticsCost).options(
            selectinload(LogisticsCost.departure_warehouse),
            selectinload(LogisticsCost.arrival_warehouse),
        )
    )
    return [_logistics_response(cost) for cost in costs]


@router.post(
    "/logistics-costs",
    response_model=LogisticsCostResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_admin],
)
def upsert_logistics_cost(
    payload: LogisticsCostCreate, db: Session = Depends(get_db)
) -> LogisticsCostResponse:
    """구간 하나에 비용 하나. 이미 있으면 갱신한다."""
    if payload.departure_warehouse_id == payload.arrival_warehouse_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="출발 창고와 도착 창고가 같습니다.",
        )
    _get_or_404(db, Warehouse, payload.departure_warehouse_id, "출발 창고")
    _get_or_404(db, Warehouse, payload.arrival_warehouse_id, "도착 창고")

    cost = db.scalar(
        select(LogisticsCost).where(
            LogisticsCost.departure_warehouse_id == payload.departure_warehouse_id,
            LogisticsCost.arrival_warehouse_id == payload.arrival_warehouse_id,
        )
    )
    if cost is None:
        cost = LogisticsCost(**payload.model_dump())
        db.add(cost)
    else:
        cost.cost_per_tu = payload.cost_per_tu

    db.commit()
    db.refresh(cost)
    return _logistics_response(cost)


@router.delete(
    "/logistics-costs/{cost_id}",
    response_model=MessageResponse,
    dependencies=[_admin],
)
def delete_logistics_cost(
    cost_id: int, db: Session = Depends(get_db)
) -> MessageResponse:
    """설정값이라 실제로 지운다. 참조하는 이력이 없다."""
    db.delete(_get_or_404(db, LogisticsCost, cost_id, "물류비"))
    db.commit()
    return MessageResponse(message="물류비를 삭제했습니다.")


# ══════════════════════════════════════════════════════════════════════
# 이관 MOQ — 창고·품목별 예외
# ══════════════════════════════════════════════════════════════════════


@router.get("/warehouse-moq", response_model=list[WarehouseMoqResponse])
def list_warehouse_moq(
    warehouse_id: int | None = None, db: Session = Depends(get_db)
) -> list[WarehouseMoqResponse]:
    stmt = select(WarehouseProductMoq)
    if warehouse_id is not None:
        stmt = stmt.where(WarehouseProductMoq.warehouse_id == warehouse_id)

    warehouses = {w.id: w.name for w in db.scalars(select(Warehouse))}
    products = {p.id: p.product_code for p in db.scalars(select(Product))}

    return [
        WarehouseMoqResponse.model_validate(moq).model_copy(
            update={
                "warehouse_name": warehouses.get(moq.warehouse_id),
                "product_code": products.get(moq.product_id),
            }
        )
        for moq in db.scalars(stmt)
    ]


@router.post(
    "/warehouse-moq",
    response_model=WarehouseMoqResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_admin],
)
def upsert_warehouse_moq(
    payload: WarehouseMoqCreate, db: Session = Depends(get_db)
) -> WarehouseMoqResponse:
    warehouse = _get_or_404(db, Warehouse, payload.warehouse_id, "창고")
    product = _get_or_404(db, Product, payload.product_id, "품목")

    moq = db.scalar(
        select(WarehouseProductMoq).where(
            WarehouseProductMoq.warehouse_id == payload.warehouse_id,
            WarehouseProductMoq.product_id == payload.product_id,
        )
    )
    if moq is None:
        moq = WarehouseProductMoq(**payload.model_dump())
        db.add(moq)
    else:
        moq.transfer_moq = payload.transfer_moq

    db.commit()
    db.refresh(moq)
    return WarehouseMoqResponse.model_validate(moq).model_copy(
        update={"warehouse_name": warehouse.name, "product_code": product.product_code}
    )


@router.delete(
    "/warehouse-moq/{moq_id}", response_model=MessageResponse, dependencies=[_admin]
)
def delete_warehouse_moq(moq_id: int, db: Session = Depends(get_db)) -> MessageResponse:
    """예외를 지우면 창고 기본 MOQ 로 돌아간다."""
    db.delete(_get_or_404(db, WarehouseProductMoq, moq_id, "이관 MOQ"))
    db.commit()
    return MessageResponse(message="이관 MOQ 예외를 삭제했습니다.")
