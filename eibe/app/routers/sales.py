"""
판매 원장 · 행사 API.

원장이 진실이고 나머지는 파생이다 (D1). 그래서 이 라우터가 판매를 바꾸면
해당 주차의 집계를 다시 만든다 — 별도 동기화 작업이 없다.

미매핑 건도 저장한다. 원본 문자열을 보존해 두었으므로 나중에 별칭을 등록하고
`/resolve` 를 부르면 재업로드 없이 해석된다.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.dates import iso_week_of
from app.core.deps import require_operator, require_viewer
from app.database import get_db
from app.models.master import Brand, Channel, ProductAlias
from app.models.sales import Promotion, SalesOrder
from app.schemas.common import MessageResponse
from app.schemas.sales import (
    PromotionCreate,
    PromotionResponse,
    ResolveResponse,
    SalesOrderCreate,
    SalesOrderResponse,
    UnmappedSourcesResponse,
)
from app.services import derive

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/sales",
    tags=["판매"],
    dependencies=[Depends(require_viewer)],
)

_operator = Depends(require_operator)


def _order_response(order: SalesOrder) -> SalesOrderResponse:
    return SalesOrderResponse.model_validate(order).model_copy(
        update={
            "product_code": order.product.product_code if order.product else None,
            "is_mapped": order.is_mapped,
        }
    )


@router.get("/orders", response_model=list[SalesOrderResponse])
def list_orders(
    brand_id: int | None = None,
    since: date | None = None,
    until: date | None = None,
    unmapped_only: bool = Query(
        False, description="품목 또는 채널이 해석되지 않은 건만"
    ),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> list[SalesOrderResponse]:
    stmt = (
        select(SalesOrder)
        .options(selectinload(SalesOrder.product))
        # 정렬 없이 자르지 않는다 — Postgres 는 페이지마다 다른 행을 줄 수 있다.
        .order_by(SalesOrder.ship_date.desc(), SalesOrder.id.desc())
        .limit(limit)
    )
    if brand_id is not None:
        stmt = stmt.where(SalesOrder.brand_id == brand_id)
    if since is not None:
        stmt = stmt.where(SalesOrder.ship_date >= since)
    if until is not None:
        stmt = stmt.where(SalesOrder.ship_date <= until)
    if unmapped_only:
        stmt = stmt.where(
            (SalesOrder.product_id.is_(None)) | (SalesOrder.channel_id.is_(None))
        )

    return [_order_response(order) for order in db.scalars(stmt)]


@router.post(
    "/orders",
    response_model=SalesOrderResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_operator],
)
def create_order(
    payload: SalesOrderCreate, db: Session = Depends(get_db)
) -> SalesOrderResponse:
    """판매 한 건 등록. 해당 주차 집계를 즉시 다시 만든다."""
    if db.get(Brand, payload.brand_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "브랜드 정보를 찾을 수 없습니다.")

    alias = db.scalar(
        select(ProductAlias).where(
            ProductAlias.source_name == payload.source_product_name
        )
    )
    channel = db.scalar(
        select(Channel).where(Channel.name == payload.source_channel_name)
    )

    week = iso_week_of(payload.ship_date)
    amount = payload.amount
    if amount is None:
        amount = (
            payload.unit_price * payload.qty
            if payload.unit_price is not None
            else Decimal("0")
        )

    order = SalesOrder(
        brand_id=payload.brand_id,
        order_no=payload.order_no,
        source_product_name=payload.source_product_name,
        source_channel_name=payload.source_channel_name,
        category=payload.category,
        product_id=alias.product_id if alias else None,
        channel_id=channel.id if channel else None,
        order_date=payload.order_date,
        ship_date=payload.ship_date,
        iso_year=week.year,
        iso_week=week.week,
        qty=payload.qty,
        unit_price=payload.unit_price,
        amount=amount,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    derive.rebuild_weekly_metrics(
        db, since=payload.ship_date, until=payload.ship_date
    )
    return _order_response(order)


@router.delete(
    "/orders/{order_id}", response_model=MessageResponse, dependencies=[_operator]
)
def delete_order(order_id: int, db: Session = Depends(get_db)) -> MessageResponse:
    order = db.get(SalesOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "판매 건을 찾을 수 없습니다.")

    ship_date = order.ship_date
    db.delete(order)
    db.commit()

    # 원장이 바뀌었으므로 그 주차를 다시 만든다.
    derive.rebuild_weekly_metrics(db, since=ship_date, until=ship_date)
    return MessageResponse(message="판매 건을 삭제하고 주차 집계를 갱신했습니다.")


@router.get("/unmapped", response_model=UnmappedSourcesResponse)
def unmapped_sources(db: Session = Depends(get_db)) -> UnmappedSourcesResponse:
    """아직 해석되지 않은 원본 값.

    이 건들은 창고를 특정할 수 없어 재고 집계에 들어가지 못한다. 총계에서
    조용히 빠지는 대신 화면에 드러낸다.
    """
    return UnmappedSourcesResponse(**derive.unmapped_sources(db))


@router.post("/resolve", response_model=ResolveResponse, dependencies=[_operator])
def resolve_mappings(
    only_unmapped: bool = Query(
        True, description="False 면 전체를 다시 해석한다 (별칭을 잘못 걸었던 경우)"
    ),
    db: Session = Depends(get_db),
) -> ResolveResponse:
    """원본 문자열을 품목·채널에 다시 연결하고 집계를 갱신한다.

    별칭을 추가한 뒤 부르면 이미 올라온 판매 건이 해석된다 — 재업로드가
    필요 없다. 그 다음 전체 주차를 다시 계산해 새로 매핑된 건을 반영한다.
    """
    updated = derive.resolve_sales_mappings(db, only_unmapped=only_unmapped)
    if updated:
        derive.rebuild_weekly_metrics(db)

    remaining = derive.unmapped_sources(db)
    return ResolveResponse(
        updated=updated,
        remaining=UnmappedSourcesResponse(**remaining),
        message=(
            f"{updated}건 해석 완료. "
            f"미매핑 제품 {len(remaining['products'])}종, 채널 {len(remaining['channels'])}종 남음"
        ),
    )


# ══════════════════════════════════════════════════════════════════════
# 행사
# ══════════════════════════════════════════════════════════════════════


@router.get("/promotions", response_model=list[PromotionResponse])
def list_promotions(
    brand_id: int | None = None,
    active_on: date | None = Query(
        default=None, description="이 날짜에 걸쳐 있는 행사만"
    ),
    db: Session = Depends(get_db),
) -> list[Promotion]:
    stmt = select(Promotion).order_by(Promotion.start_date.desc(), Promotion.id)
    if brand_id is not None:
        stmt = stmt.where(Promotion.brand_id == brand_id)
    if active_on is not None:
        stmt = stmt.where(
            Promotion.start_date <= active_on, Promotion.end_date >= active_on
        )
    return list(db.scalars(stmt))


@router.post(
    "/promotions",
    response_model=PromotionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_operator],
)
def create_promotion(
    payload: PromotionCreate, db: Session = Depends(get_db)
) -> Promotion:
    if payload.end_date < payload.start_date:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "종료일이 시작일보다 빠릅니다."
        )
    if db.get(Brand, payload.brand_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "브랜드 정보를 찾을 수 없습니다.")

    alias = (
        db.scalar(
            select(ProductAlias).where(
                ProductAlias.source_name == payload.source_product_name
            )
        )
        if payload.source_product_name
        else None
    )
    channel = db.scalar(
        select(Channel).where(Channel.name == payload.source_channel_name)
    )

    promotion = Promotion(
        **payload.model_dump(),
        product_id=alias.product_id if alias else None,
        channel_id=channel.id if channel else None,
    )
    db.add(promotion)
    db.commit()
    db.refresh(promotion)
    return promotion


@router.delete(
    "/promotions/{promotion_id}",
    response_model=MessageResponse,
    dependencies=[_operator],
)
def delete_promotion(
    promotion_id: int, db: Session = Depends(get_db)
) -> MessageResponse:
    promotion = db.get(Promotion, promotion_id)
    if promotion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "행사를 찾을 수 없습니다.")
    db.delete(promotion)
    db.commit()
    return MessageResponse(message="행사를 삭제했습니다.")
