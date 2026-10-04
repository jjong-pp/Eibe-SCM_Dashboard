"""
재고 API — 스냅샷 · 재고일수 히트맵 · 유통기한 · 이관.

구 버전은 이 라우터가 849줄이었고 계산이 전부 안에 있었다. 여기서는
`services/inventory.py` 가 값을 만들고, 라우터는 권한·검증·직렬화만 한다.

권한: 조회는 로그인만, 등록·수정은 운영자 이상. 기준 정보와 달리 재고는
업무 데이터라 관리자까지 요구하지 않는다.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import require_operator, require_viewer
from app.database import get_db
from app.models.master import Product, Warehouse
from app.models.scm import InventorySnapshot
from app.schemas.common import MessageResponse
from app.schemas.scm import (
    ExpiryLotResponse,
    ExpiryReportResponse,
    SnapshotCreate,
    SnapshotResponse,
    StockPositionResponse,
    StockSummaryResponse,
    TransferPlanResponse,
    TransferSuggestionResponse,
    nullable_weeks,
)
from app.services import forecasting, inventory

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/inventory",
    tags=["재고"],
    dependencies=[Depends(require_viewer)],
)

_operator = Depends(require_operator)


# ══════════════════════════════════════════════════════════════════════
# 스냅샷 CRUD
# ══════════════════════════════════════════════════════════════════════


def _snapshot_response(
    snapshot: InventorySnapshot,
) -> SnapshotResponse:
    return SnapshotResponse.model_validate(snapshot).model_copy(
        update={
            "warehouse_name": snapshot.warehouse.name if snapshot.warehouse else None,
            "product_code": snapshot.product.product_code if snapshot.product else None,
        }
    )


@router.get("/snapshots", response_model=list[SnapshotResponse])
def list_snapshots(
    snapshot_date: date | None = None,
    warehouse_id: int | None = None,
    product_id: int | None = None,
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> list[SnapshotResponse]:
    """재고 스냅샷 조회.

    정렬 없이 자르지 않는다 — SQLite 는 우연히 일관되지만 Postgres 는
    페이지마다 다른 행을 돌려줄 수 있다.
    """
    stmt = (
        select(InventorySnapshot)
        .options(
            selectinload(InventorySnapshot.warehouse),
            selectinload(InventorySnapshot.product),
        )
        .order_by(
            InventorySnapshot.snapshot_date.desc(),
            InventorySnapshot.warehouse_id,
            InventorySnapshot.product_id,
            InventorySnapshot.id,
        )
        .limit(limit)
    )
    if snapshot_date is not None:
        stmt = stmt.where(InventorySnapshot.snapshot_date == snapshot_date)
    if warehouse_id is not None:
        stmt = stmt.where(InventorySnapshot.warehouse_id == warehouse_id)
    if product_id is not None:
        stmt = stmt.where(InventorySnapshot.product_id == product_id)

    return [_snapshot_response(row) for row in db.scalars(stmt)]


@router.post(
    "/snapshots",
    response_model=SnapshotResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_operator],
)
def create_snapshot(
    payload: SnapshotCreate, db: Session = Depends(get_db)
) -> SnapshotResponse:
    """스냅샷 등록.

    같은 (일자, 창고, 품목, 기한) 이 이미 있으면 수량을 갱신한다. 스냅샷은
    그 시점의 사실이므로 같은 로트에 두 값이 있을 수 없다.
    """
    if db.get(Warehouse, payload.warehouse_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "창고 정보를 찾을 수 없습니다.")
    if db.get(Product, payload.product_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "품목 정보를 찾을 수 없습니다.")

    existing = db.scalar(
        select(InventorySnapshot).where(
            InventorySnapshot.snapshot_date == payload.snapshot_date,
            InventorySnapshot.warehouse_id == payload.warehouse_id,
            InventorySnapshot.product_id == payload.product_id,
            InventorySnapshot.expiry_date == payload.expiry_date,
        )
    )
    if existing is not None:
        existing.qty = payload.qty
        db.commit()
        db.refresh(existing)
        return _snapshot_response(existing)

    snapshot = InventorySnapshot(**payload.model_dump())
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return _snapshot_response(snapshot)


@router.delete(
    "/snapshots/{snapshot_id}",
    response_model=MessageResponse,
    dependencies=[_operator],
)
def delete_snapshot(
    snapshot_id: int, db: Session = Depends(get_db)
) -> MessageResponse:
    """잘못 올린 스냅샷은 지운다. 파생 집계는 재계산으로 복구된다."""
    snapshot = db.get(InventorySnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "스냅샷을 찾을 수 없습니다.")
    db.delete(snapshot)
    db.commit()
    return MessageResponse(message="스냅샷을 삭제했습니다.")


# ══════════════════════════════════════════════════════════════════════
# 재고일수 히트맵
# ══════════════════════════════════════════════════════════════════════


@router.get("/summary", response_model=StockSummaryResponse)
def stock_summary(
    as_of: date | None = None,
    by_warehouse: bool = True,
    brand_id: int | None = None,
    include_empty: bool = False,
    db: Session = Depends(get_db),
) -> StockSummaryResponse:
    """재고일수 히트맵.

    구간 경계를 응답에 함께 실어보낸다. 화면 범례가 상수를 따로 들고 있으면
    서버 기준이 바뀔 때 조용히 어긋난다.
    """
    reference = as_of or date.today()
    positions = inventory.stock_summary(
        db,
        as_of=reference,
        by_warehouse=by_warehouse,
        brand_id=brand_id,
        include_empty=include_empty,
    )

    return StockSummaryResponse(
        as_of=reference,
        thresholds_weeks=list(forecasting.RISK_THRESHOLDS_WEEKS),
        positions=[
            StockPositionResponse(
                product_id=position.product_id,
                product_code=position.product_code,
                product_name=position.product_name,
                warehouse_id=position.warehouse_id,
                warehouse_name=position.warehouse_name,
                qty=position.qty,
                snapshot_date=position.snapshot_date,
                weekly_demand=position.weekly_demand,
                smoothing_constant=position.smoothing_constant,
                loss_buffer=position.loss_buffer,
                weeks_of_supply=nullable_weeks(position.weeks_of_supply),
                risk=position.risk.value,
                expiry_label=position.expiry_label,
            )
            for position in positions
        ],
    )


# ══════════════════════════════════════════════════════════════════════
# 유통기한 (FEFO)
# ══════════════════════════════════════════════════════════════════════


@router.get("/expiry", response_model=ExpiryReportResponse)
def expiry_report(
    as_of: date | None = None,
    warehouse_id: int | None = None,
    at_risk_only: bool = False,
    db: Session = Depends(get_db),
) -> ExpiryReportResponse:
    """FEFO 기준 기한 현황.

    `is_judgeable=False` 인 로트는 소진 이력이 없어 판정하지 못한 것이다.
    '위험 없음'과 구분해서 보여줘야 한다.
    """
    reference = as_of or date.today()
    lots = inventory.expiry_report(
        db, as_of=reference, warehouse_id=warehouse_id, at_risk_only=at_risk_only
    )

    return ExpiryReportResponse(
        as_of=reference,
        at_risk_count=sum(1 for lot in lots if lot.is_at_risk),
        unjudged_count=sum(1 for lot in lots if not lot.is_judgeable),
        lots=[
            ExpiryLotResponse(
                product_id=lot.product_id,
                product_code=lot.product_code,
                product_name=lot.product_name,
                warehouse_id=lot.warehouse_id,
                warehouse_name=lot.warehouse_name,
                expiry_date=lot.expiry_date,
                qty=lot.qty,
                qty_ahead=lot.qty_ahead,
                days_remaining=lot.days_remaining,
                weeks_to_clear=nullable_weeks(lot.weeks_to_clear),
                is_at_risk=lot.is_at_risk,
                is_judgeable=lot.is_judgeable,
                expiry_label=lot.expiry_label,
            )
            for lot in lots
        ],
    )


# ══════════════════════════════════════════════════════════════════════
# 이관 시뮬레이션
# ══════════════════════════════════════════════════════════════════════


@router.get("/transfer-plan", response_model=TransferPlanResponse)
def transfer_plan(
    as_of: date | None = None,
    target_weeks: float = Query(
        inventory.TRANSFER_TARGET_WEEKS, gt=0, le=52,
        description="이 주수까지 채운다",
    ),
    db: Session = Depends(get_db),
) -> TransferPlanResponse:
    """용인 메인창고(HUB) → 풀필먼트 창고 이관 제안.

    조회 전용이다 — 실제 이관은 재고 스냅샷으로 반영된다. 계산 결과를
    저장해두면 재고가 바뀐 뒤에도 낡은 제안이 남는다.
    """
    reference = as_of or date.today()
    plan = inventory.simulate_transfers(
        db, as_of=reference, target_weeks=target_weeks
    )

    return TransferPlanResponse(
        as_of=reference,
        target_weeks=target_weeks,
        total_qty=plan.total_qty,
        suggestions=[
            TransferSuggestionResponse(
                product_id=item.product_id,
                product_code=item.product_code,
                product_name=item.product_name,
                from_warehouse_id=item.from_warehouse_id,
                from_warehouse_name=item.from_warehouse_name,
                to_warehouse_id=item.to_warehouse_id,
                to_warehouse_name=item.to_warehouse_name,
                current_qty=item.current_qty,
                weekly_demand=item.weekly_demand,
                weeks_of_supply=nullable_weeks(item.weeks_of_supply),
                shortage_qty=item.shortage_qty,
                suggested_qty=item.suggested_qty,
                moq=item.moq,
                limited_by_hub=item.limited_by_hub,
                cost=item.cost,
            )
            for item in plan.suggestions
        ],
        shortfalls=plan.shortfalls,
    )
