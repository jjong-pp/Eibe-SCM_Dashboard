"""
발주 계획.

업무 규칙: **리드타임을 고려해 6개월 뒤 도착분을 주문한다.** 그래서 발주월
(target_month)과 도착월(arrival_month)이 다르고, 화면에도 둘 다 보여야 한다 —
"이번 달에 넣는 주문이 언제 들어오는가"를 실무자가 늘 확인하기 때문이다.

계산은 `forecasting` 이 하고 여기서는 DB 에서 재료를 모아 넘긴다. 예측 자체는
사칙연산뿐이라 실무자가 손으로 따라갈 수 있어야 하며, 이 모듈은 그 입력값
(현재고 · 입고예정 · 주간수요)이 어디서 왔는지를 그대로 드러낸다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.dates import add_months, iso_week_of, month_key
from app.models.enums import InboundStatus, PlanStatus
from app.models.master import Product
from app.models.scm import Inbound, MonthlyOrderPlan
from app.services import derive, forecasting

logger = logging.getLogger(__name__)

#: 발주부터 도착까지. 업무 규칙상 6개월 뒤 도착분을 주문한다.
ORDER_LEAD_MONTHS = 6


@dataclass(frozen=True, slots=True)
class ProductPlan:
    """품목 하나의 발주 제안. 근거가 되는 중간값을 모두 들고 있다."""

    product_id: int
    product_code: str
    product_name: str
    current_stock: int
    #: 예측 입력 — 화면에서 근거로 보여준다
    smoothing_constant: float
    loss_buffer: float
    weekly_demand: float
    weeks_of_supply: float
    risk: forecasting.StockRisk
    #: {주차번호: 수량} — 시뮬레이션 구간 안에 도착 예정인 입고
    scheduled_inbounds: dict[int, int]
    suggested_qty: int
    #: 발주 단위(카툰당 입수량)의 배수로 올린 값이다
    order_unit: int
    final_stock: float
    first_stockout_week: int | None
    air_shipment: forecasting.AirShipmentAlert | None
    target_month: str
    arrival_month: str


@dataclass(frozen=True, slots=True)
class OrderPlanSimulation:
    target_month: str
    arrival_month: str
    horizon_weeks: int
    plans: list[ProductPlan] = field(default_factory=list)

    @property
    def total_suggested_qty(self) -> int:
        return sum(plan.suggested_qty for plan in self.plans)

    @property
    def urgent(self) -> list[ProductPlan]:
        """항공 전환 검토가 필요한 품목."""
        return [plan for plan in self.plans if plan.air_shipment is not None]


def _scheduled_inbounds(
    db: Session, product_id: int, start: date, horizon: int
) -> dict[int, int]:
    """시뮬레이션 구간에 도착 예정인 입고를 주차번호로 묶는다.

    이미 입고완료된 건은 뺀다 — 그 수량은 현재고에 이미 반영되어 있어서
    두 번 세면 재고를 과대평가한다.
    """
    anchor = iso_week_of(start)
    buckets: dict[int, int] = {}

    rows = db.scalars(
        select(Inbound).where(
            Inbound.product_id == product_id,
            Inbound.eta.is_not(None),
            Inbound.eta >= start,
            Inbound.status != InboundStatus.RECEIVED,
        )
    )
    for inbound in rows:
        eta_week = iso_week_of(inbound.eta)
        offset = (eta_week.start_date() - anchor.start_date()).days // 7 + 1
        if 1 <= offset <= horizon:
            buckets[offset] = buckets.get(offset, 0) + inbound.unit_qty

    return buckets


def simulate_order_plan(
    db: Session,
    *,
    as_of: date | None = None,
    horizon: int = forecasting.DEFAULT_HORIZON_WEEKS,
    safety_stock_weeks: float = forecasting.DEFAULT_SAFETY_STOCK_WEEKS,
    weight_factor: float = 1.0,
    brand_id: int | None = None,
) -> OrderPlanSimulation:
    """전 품목 발주 시뮬레이션.

    Args:
        weight_factor: 수요 가중치. 실무자가 성수기·프로모션을 반영해 조정한다.
            감모 버퍼에는 곱하지 않는다 (판매량과 무관한 고정 손실로 본다).
    """
    reference = as_of or date.today()
    anchor = iso_week_of(reference)

    stock = derive.stock_on(db, reference)
    totals: dict[int, int] = {}
    for (product_id, _warehouse_id), (qty, _snapshot_date) in stock.items():
        totals[product_id] = totals.get(product_id, 0) + qty

    conditions = [Product.is_active.is_(True)]
    if brand_id is not None:
        conditions.append(Product.brand_id == brand_id)

    target = month_key(reference)
    arrival = month_key(add_months(reference, ORDER_LEAD_MONTHS))

    plans: list[ProductPlan] = []
    for product in db.scalars(
        select(Product).options(selectinload(Product.brand)).where(*conditions)
        .order_by(Product.product_code)
    ):
        outflow, sales = derive.load_history(db, product.id, anchor)
        smoothing = forecasting.calc_smoothing_constant(outflow)
        buffer = forecasting.calc_loss_buffer(outflow, sales)
        current = totals.get(product.id, 0)
        inbounds = _scheduled_inbounds(db, product.id, reference, horizon)

        simulation = forecasting.simulate_inventory(
            current_stock=current,
            smoothing_constant=smoothing,
            loss_buffer=buffer,
            scheduled_inbounds=inbounds,
            weight_factor=weight_factor,
            horizon=horizon,
        )

        # 발주는 카툰 단위로 나간다. 낱개 수량을 그대로 주문할 수 없다.
        order_unit = product.pack_qty_per_tu
        suggested = forecasting.suggest_order_qty(
            simulation, moq=order_unit, safety_stock_weeks=safety_stock_weeks
        )

        plans.append(
            ProductPlan(
                product_id=product.id,
                product_code=product.product_code,
                product_name=product.name,
                current_stock=current,
                smoothing_constant=simulation.smoothing_constant,
                loss_buffer=simulation.loss_buffer,
                weekly_demand=simulation.weekly_demand,
                weeks_of_supply=simulation.weeks_of_supply,
                risk=simulation.risk,
                scheduled_inbounds=inbounds,
                suggested_qty=suggested,
                order_unit=order_unit,
                final_stock=simulation.final_stock,
                first_stockout_week=simulation.first_stockout_week,
                air_shipment=forecasting.check_air_shipment(simulation),
                target_month=target,
                arrival_month=arrival,
            )
        )

    return OrderPlanSimulation(
        target_month=target,
        arrival_month=arrival,
        horizon_weeks=horizon,
        plans=plans,
    )


def save_plans(
    db: Session,
    target_month: str,
    quantities: dict[int, int],
    *,
    arrival_month: str | None = None,
) -> tuple[int, int]:
    """제안을 계획으로 저장한다. (신규, 갱신) 건수를 돌려준다.

    확정(CONFIRMED)된 계획은 건드리지 않는다 — 이미 발주번호가 붙어 나간
    주문이므로, 재시뮬레이션 결과로 수량이 바뀌면 발주와 기록이 어긋난다.
    """
    created = updated = 0

    for product_id, qty in quantities.items():
        plan = db.scalar(
            select(MonthlyOrderPlan).where(
                MonthlyOrderPlan.target_month == target_month,
                MonthlyOrderPlan.product_id == product_id,
            )
        )
        if plan is None:
            db.add(
                MonthlyOrderPlan(
                    target_month=target_month,
                    arrival_month=arrival_month,
                    product_id=product_id,
                    system_suggested_qty=qty,
                    user_modified_qty=qty,
                    status=PlanStatus.DRAFT,
                )
            )
            created += 1
        elif plan.status is PlanStatus.CONFIRMED:
            logger.info("확정된 계획은 건너뜁니다: %s / %s", target_month, product_id)
        else:
            plan.system_suggested_qty = qty
            plan.user_modified_qty = qty
            plan.arrival_month = arrival_month or plan.arrival_month
            plan.version += 1
            updated += 1

    db.commit()
    return created, updated
