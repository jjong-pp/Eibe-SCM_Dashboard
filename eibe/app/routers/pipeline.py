"""
입고 파이프라인 · 발주 계획 API.

구 스키마는 발주(`ORDER_DB`)와 계획(`MONTHLY_ORDER_PLAN`)을 따로 뒀는데 같은
사실을 두 곳에 저장하는 구조였다 (D11). 여기서는 확정된 계획이 곧 주문이고,
`purchase_code` 가 입고 레코드와 이어져 발주 → 입고 추적이 끊기지 않는다.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import require_operator, require_viewer
from app.database import get_db
from app.models.enums import InboundStatus, PlanStatus
from app.models.master import Product, Warehouse
from app.models.scm import Inbound, MonthlyOrderPlan
from app.schemas.common import MessageResponse
from app.schemas.scm import (
    AirShipmentResponse,
    InboundCreate,
    InboundResponse,
    InboundUpdate,
    OrderPlanResponse,
    OrderPlanSaveRequest,
    OrderPlanSimulationResponse,
    OrderPlanUpdate,
    ProductPlanResponse,
    nullable_weeks,
)
from app.services import planning

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["공급망"],
    dependencies=[Depends(require_viewer)],
)

_operator = Depends(require_operator)


# ══════════════════════════════════════════════════════════════════════
# 입고
# ══════════════════════════════════════════════════════════════════════


def _inbound_response(inbound: Inbound) -> InboundResponse:
    return InboundResponse.model_validate(inbound).model_copy(
        update={
            "product_code": inbound.product.product_code if inbound.product else None,
            "product_name": inbound.product.name if inbound.product else None,
            "arrival_warehouse_name": (
                inbound.arrival_warehouse.name if inbound.arrival_warehouse else None
            ),
            "status_order": InboundStatus(inbound.status).order,
        }
    )


@router.get("/inbound", response_model=list[InboundResponse])
def list_inbound(
    status_filter: InboundStatus | None = Query(default=None, alias="status"),
    product_id: int | None = None,
    pending_only: bool = Query(
        False, description="입고완료를 제외한 진행 중인 건만"
    ),
    db: Session = Depends(get_db),
) -> list[InboundResponse]:
    stmt = (
        select(Inbound)
        .options(
            selectinload(Inbound.product), selectinload(Inbound.arrival_warehouse)
        )
        .order_by(Inbound.eta.is_(None), Inbound.eta, Inbound.id)
    )
    if status_filter is not None:
        stmt = stmt.where(Inbound.status == status_filter)
    if product_id is not None:
        stmt = stmt.where(Inbound.product_id == product_id)
    if pending_only:
        stmt = stmt.where(Inbound.status != InboundStatus.RECEIVED)

    return [_inbound_response(row) for row in db.scalars(stmt)]


@router.post(
    "/inbound",
    response_model=InboundResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_operator],
)
def create_inbound(
    payload: InboundCreate, db: Session = Depends(get_db)
) -> InboundResponse:
    if db.get(Product, payload.product_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "품목 정보를 찾을 수 없습니다.")
    if payload.arrival_warehouse_id is not None:
        if db.get(Warehouse, payload.arrival_warehouse_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "창고 정보를 찾을 수 없습니다.")

    inbound = Inbound(**payload.model_dump())
    db.add(inbound)
    db.commit()
    db.refresh(inbound)
    logger.info("입고 등록: %s", inbound.invoice_no or inbound.id)
    return _inbound_response(inbound)


@router.put(
    "/inbound/{inbound_id}", response_model=InboundResponse, dependencies=[_operator]
)
def update_inbound(
    inbound_id: int, payload: InboundUpdate, db: Session = Depends(get_db)
) -> InboundResponse:
    inbound = db.get(Inbound, inbound_id)
    if inbound is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "입고 정보를 찾을 수 없습니다.")

    for attribute, value in payload.model_dump(exclude_unset=True).items():
        setattr(inbound, attribute, value)

    db.commit()
    db.refresh(inbound)
    return _inbound_response(inbound)


@router.delete(
    "/inbound/{inbound_id}", response_model=MessageResponse, dependencies=[_operator]
)
def delete_inbound(inbound_id: int, db: Session = Depends(get_db)) -> MessageResponse:
    inbound = db.get(Inbound, inbound_id)
    if inbound is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "입고 정보를 찾을 수 없습니다.")
    db.delete(inbound)
    db.commit()
    return MessageResponse(message="입고 건을 삭제했습니다.")


# ══════════════════════════════════════════════════════════════════════
# 발주 계획
# ══════════════════════════════════════════════════════════════════════


@router.get("/order-plan/simulation", response_model=OrderPlanSimulationResponse)
def order_plan_simulation(
    as_of: date | None = None,
    weight_factor: float = Query(1.0, gt=0, le=10, description="수요 가중치"),
    safety_stock_weeks: float = Query(6.0, ge=0, le=52),
    brand_id: int | None = None,
    db: Session = Depends(get_db),
) -> OrderPlanSimulationResponse:
    """발주 시뮬레이션.

    저장하지 않는다. 가중치를 바꿔가며 즉시 다시 볼 수 있어야 하므로
    조회 시점에 계산한다.
    """
    simulation = planning.simulate_order_plan(
        db,
        as_of=as_of,
        safety_stock_weeks=safety_stock_weeks,
        weight_factor=weight_factor,
        brand_id=brand_id,
    )

    return OrderPlanSimulationResponse(
        target_month=simulation.target_month,
        arrival_month=simulation.arrival_month,
        horizon_weeks=simulation.horizon_weeks,
        total_suggested_qty=simulation.total_suggested_qty,
        urgent_count=len(simulation.urgent),
        plans=[
            ProductPlanResponse(
                product_id=plan.product_id,
                product_code=plan.product_code,
                product_name=plan.product_name,
                current_stock=plan.current_stock,
                smoothing_constant=plan.smoothing_constant,
                loss_buffer=plan.loss_buffer,
                weekly_demand=plan.weekly_demand,
                weeks_of_supply=nullable_weeks(plan.weeks_of_supply),
                risk=plan.risk.value,
                scheduled_inbounds=plan.scheduled_inbounds,
                suggested_qty=plan.suggested_qty,
                order_unit=plan.order_unit,
                final_stock=plan.final_stock,
                first_stockout_week=plan.first_stockout_week,
                air_shipment=(
                    AirShipmentResponse(
                        week=plan.air_shipment.week,
                        shortage_qty=plan.air_shipment.shortage_qty,
                        message=plan.air_shipment.message,
                    )
                    if plan.air_shipment
                    else None
                ),
                target_month=plan.target_month,
                arrival_month=plan.arrival_month,
            )
            for plan in simulation.plans
        ],
    )


def _plan_response(plan: MonthlyOrderPlan) -> OrderPlanResponse:
    return OrderPlanResponse.model_validate(plan).model_copy(
        update={
            "product_code": plan.product.product_code if plan.product else None,
            "product_name": plan.product.name if plan.product else None,
        }
    )


@router.get("/order-plan", response_model=list[OrderPlanResponse])
def list_order_plans(
    target_month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
) -> list[OrderPlanResponse]:
    stmt = (
        select(MonthlyOrderPlan)
        .options(selectinload(MonthlyOrderPlan.product))
        .order_by(MonthlyOrderPlan.target_month.desc(), MonthlyOrderPlan.product_id)
    )
    if target_month is not None:
        stmt = stmt.where(MonthlyOrderPlan.target_month == target_month)
    return [_plan_response(plan) for plan in db.scalars(stmt)]


@router.post(
    "/order-plan", response_model=MessageResponse, dependencies=[_operator]
)
def save_order_plan(
    payload: OrderPlanSaveRequest, db: Session = Depends(get_db)
) -> MessageResponse:
    """시뮬레이션 결과를 계획으로 저장한다.

    확정된 계획은 건드리지 않는다 — 이미 발주번호가 붙어 나간 주문이므로
    재시뮬레이션 결과로 수량이 바뀌면 발주와 기록이 어긋난다.
    """
    unknown = [
        product_id
        for product_id in payload.quantities
        if db.get(Product, product_id) is None
    ]
    if unknown:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"등록되지 않은 품목이 있습니다: {unknown}",
        )

    created, updated = planning.save_plans(
        db,
        payload.target_month,
        payload.quantities,
        arrival_month=payload.arrival_month,
    )
    return MessageResponse(
        message=f"발주 계획 저장 완료 — 신규 {created}건, 갱신 {updated}건"
    )


@router.put(
    "/order-plan/{plan_id}", response_model=OrderPlanResponse, dependencies=[_operator]
)
def update_order_plan(
    plan_id: int, payload: OrderPlanUpdate, db: Session = Depends(get_db)
) -> OrderPlanResponse:
    """계획 수정. 실무자가 조정한 수량이 시스템 제안보다 우선한다.

    `version` 을 함께 보내면 낙관적 잠금이 걸린다. 다른 사람이 먼저 고쳤으면
    409 로 돌려보내 덮어쓰기를 막는다.
    """
    plan = db.get(MonthlyOrderPlan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "발주 계획을 찾을 수 없습니다.")

    changes = payload.model_dump(exclude_unset=True)
    expected = changes.pop("version", None)
    if expected is not None and expected != plan.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "다른 사용자가 먼저 수정했습니다. 새로고침 후 다시 시도하세요.",
        )

    if plan.status is PlanStatus.CONFIRMED and "user_modified_qty" in changes:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "확정된 계획의 수량은 변경할 수 없습니다.",
        )

    for attribute, value in changes.items():
        setattr(plan, attribute, value)
    plan.version += 1

    db.commit()
    db.refresh(plan)
    return _plan_response(plan)


@router.delete(
    "/order-plan/{plan_id}", response_model=MessageResponse, dependencies=[_operator]
)
def delete_order_plan(plan_id: int, db: Session = Depends(get_db)) -> MessageResponse:
    plan = db.get(MonthlyOrderPlan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "발주 계획을 찾을 수 없습니다.")
    if plan.status is PlanStatus.CONFIRMED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "확정된 계획은 삭제할 수 없습니다. 발주번호가 부여된 주문입니다.",
        )
    db.delete(plan)
    db.commit()
    return MessageResponse(message="발주 계획을 삭제했습니다.")
