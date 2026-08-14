"""
재고 현황 · 유통기한 · 이관.

구 버전은 이 계산이 전부 `routers/inventory.py`(849줄) 안에 있었다. 라우터가
계산을 들고 있으면 테스트할 때마다 HTTP 를 거쳐야 하고, 같은 규칙이 화면마다
조금씩 다르게 구현된다. 여기서는 서비스가 값을 만들고 라우터는 계약만 맡는다.

세 가지를 계산한다:

  재고 현황   현재고 + 주간 소진율 → 재고일수 → 위험 구간 (히트맵)
  유통기한    FEFO 기준으로 로트를 소진 순서대로 세워, 기한 안에 다 못 나갈
              로트를 찾는다
  이관        용인 메인창고(HUB) → 각 풀필먼트 창고. 부족한 만큼, MOQ 배수로

재고일수 구간은 `forecasting.RISK_THRESHOLDS_WEEKS` 하나만 쓴다. 화면 범례와
어긋나면 안 되는 값이라 여기서 다시 정의하지 않는다.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.dates import IsoWeek, iso_week_of
from app.models.enums import BrandCategory, WarehouseType
from app.models.master import Product, Warehouse, WarehouseProductMoq
from app.models.scm import InventorySnapshot
from app.services import derive, forecasting

logger = logging.getLogger(__name__)

#: 이관 판단 기준 — 이 주수 아래로 떨어지면 채운다. 적정(13주)보다 낮게 잡아
#: 여유 있는 거점까지 흔들지 않는다.
TRANSFER_TARGET_WEEKS = 9.0

#: 유통기한 경고 기준. 이 안에 소진되지 않으면 폐기 위험으로 본다.
EXPIRY_WARNING_DAYS = 90


# ══════════════════════════════════════════════════════════════════════
# 재고 현황
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class StockPosition:
    """(품목 × 창고) 한 칸. warehouse_id 가 None 이면 전사 합계다."""

    product_id: int
    product_code: str
    product_name: str
    brand_category: BrandCategory
    warehouse_id: int | None
    warehouse_name: str | None
    qty: int
    #: 어느 날짜의 스냅샷을 썼는가. 오래됐으면 화면에서 경고할 수 있다.
    snapshot_date: date | None
    weekly_demand: float
    smoothing_constant: float
    loss_buffer: float
    #: 소진율이 0이면 math.inf — 화면은 '소진 불가'로 표시한다.
    weeks_of_supply: float
    risk: forecasting.StockRisk

    @property
    def is_depletable(self) -> bool:
        return not math.isinf(self.weeks_of_supply)

    @property
    def expiry_label(self) -> str:
        return self.brand_category.expiry_label


def _demand_for(
    db: Session,
    product_id: int,
    anchor: IsoWeek,
    *,
    warehouse_id: int | None = None,
) -> tuple[float, float, float]:
    """(주간수요, 평탄화상수, 감모버퍼).

    주간수요 = 평탄화상수 + 감모버퍼. 가중치는 시뮬레이션에서만 곱하므로
    현황 화면에는 조정 없는 값이 보인다.
    """
    outflow, sales = derive.load_history(
        db, product_id, anchor, warehouse_id=warehouse_id
    )
    smoothing = forecasting.calc_smoothing_constant(outflow)
    buffer = forecasting.calc_loss_buffer(outflow, sales)
    return smoothing + buffer, smoothing, buffer


def stock_summary(
    db: Session,
    *,
    as_of: date | None = None,
    by_warehouse: bool = True,
    brand_id: int | None = None,
    include_empty: bool = False,
) -> list[StockPosition]:
    """재고일수 히트맵의 원본 데이터.

    Args:
        by_warehouse: False 면 창고를 합산해 품목 한 줄로 돌려준다.
        include_empty: 재고가 0인 칸도 포함할지. 기본은 뺀다 — 취급하지 않는
            창고까지 격자를 채우면 화면이 못 쓰게 된다.
    """
    reference = as_of or date.today()
    anchor = iso_week_of(reference)

    products = {
        product.id: product
        for product in db.scalars(
            select(Product)
            .options(selectinload(Product.brand))
            .where(*([Product.brand_id == brand_id] if brand_id is not None else []))
        )
    }
    warehouses = {w.id: w for w in db.scalars(select(Warehouse))}
    stock = derive.stock_on(db, reference)

    positions: list[StockPosition] = []

    if by_warehouse:
        for (product_id, warehouse_id), (qty, snapshot_date) in sorted(stock.items()):
            product = products.get(product_id)
            warehouse = warehouses.get(warehouse_id)
            if product is None or warehouse is None:
                continue
            if qty == 0 and not include_empty:
                continue

            demand, smoothing, buffer = _demand_for(
                db, product_id, anchor, warehouse_id=warehouse_id
            )
            supply = forecasting.weeks_of_supply(qty, demand)
            positions.append(
                StockPosition(
                    product_id=product_id,
                    product_code=product.product_code,
                    product_name=product.name,
                    brand_category=product.brand.category,
                    warehouse_id=warehouse_id,
                    warehouse_name=warehouse.name,
                    qty=qty,
                    snapshot_date=snapshot_date,
                    weekly_demand=round(demand, 1),
                    smoothing_constant=round(smoothing, 1),
                    loss_buffer=round(buffer, 2),
                    weeks_of_supply=supply,
                    risk=forecasting.classify_stock_risk(supply),
                )
            )
        return positions

    # 전사 합계 — 창고별 재고를 품목 단위로 모은다.
    totals: dict[int, tuple[int, date | None]] = {}
    for (product_id, _warehouse_id), (qty, snapshot_date) in stock.items():
        current_qty, current_date = totals.get(product_id, (0, None))
        latest = max(filter(None, [current_date, snapshot_date]), default=None)
        totals[product_id] = (current_qty + qty, latest)

    for product_id, product in sorted(products.items()):
        qty, snapshot_date = totals.get(product_id, (0, None))
        if qty == 0 and not include_empty:
            continue

        demand, smoothing, buffer = _demand_for(db, product_id, anchor)
        supply = forecasting.weeks_of_supply(qty, demand)
        positions.append(
            StockPosition(
                product_id=product_id,
                product_code=product.product_code,
                product_name=product.name,
                brand_category=product.brand.category,
                warehouse_id=None,
                warehouse_name=None,
                qty=qty,
                snapshot_date=snapshot_date,
                weekly_demand=round(demand, 1),
                smoothing_constant=round(smoothing, 1),
                loss_buffer=round(buffer, 2),
                weeks_of_supply=supply,
                risk=forecasting.classify_stock_risk(supply),
            )
        )
    return positions


# ══════════════════════════════════════════════════════════════════════
# 유통기한 — FEFO
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ExpiryLot:
    """기한이 붙은 재고 한 로트.

    FEFO(선입선출) 이므로 기한이 이른 로트부터 나간다. 그래서 어떤 로트가
    위험한지는 **그 앞에 쌓인 물량까지 합쳐서** 봐야 한다 — 뒤에 있는 로트는
    앞의 것이 다 빠진 뒤에야 소진되기 시작한다.
    """

    product_id: int
    product_code: str
    product_name: str
    brand_category: BrandCategory
    warehouse_id: int
    warehouse_name: str
    expiry_date: date | None
    qty: int
    #: 이 로트 앞에 놓인(더 먼저 나갈) 물량
    qty_ahead: int
    days_remaining: int | None
    #: 이 로트를 다 소진하는 데 걸리는 주수. 소진율이 0이면 inf.
    weeks_to_clear: float
    is_at_risk: bool
    #: 판정할 근거가 있었는가. 기한이 없거나 소진 이력이 없으면 False 이고,
    #: 이때 is_at_risk 는 '위험 없음'이 아니라 '모름'이다.
    is_judgeable: bool

    @property
    def expiry_label(self) -> str:
        return self.brand_category.expiry_label


def expiry_report(
    db: Session,
    *,
    as_of: date | None = None,
    warehouse_id: int | None = None,
    at_risk_only: bool = False,
) -> list[ExpiryLot]:
    """FEFO 기준 유통기한 현황.

    기한이 없는 로트(전자제품 등 미입력)는 위험 판정에서 제외한다. 판단할
    근거가 없는 것을 위험하다고 표시하면 진짜 위험이 묻힌다.
    """
    reference = as_of or date.today()
    anchor = iso_week_of(reference)

    products = {
        product.id: product
        for product in db.scalars(select(Product).options(selectinload(Product.brand)))
    }
    warehouses = {w.id: w for w in db.scalars(select(Warehouse))}

    # 가장 최근 스냅샷 일자를 (품목,창고)별로 확인한 뒤 그 날짜의 로트만 읽는다.
    latest = derive.stock_on(db, reference)
    if not latest:
        return []

    conditions = []
    if warehouse_id is not None:
        conditions.append(InventorySnapshot.warehouse_id == warehouse_id)

    rows = db.scalars(
        select(InventorySnapshot)
        .where(*conditions)
        .order_by(InventorySnapshot.expiry_date.is_(None), InventorySnapshot.expiry_date)
    ).all()

    # (품목,창고)별로 그 시점의 스냅샷만 남긴다.
    grouped: dict[tuple[int, int], list[InventorySnapshot]] = {}
    for snapshot in rows:
        key = (snapshot.product_id, snapshot.warehouse_id)
        used = latest.get(key)
        if used is None or snapshot.snapshot_date != used[1] or snapshot.qty <= 0:
            continue
        grouped.setdefault(key, []).append(snapshot)

    lots: list[ExpiryLot] = []
    demand_cache: dict[tuple[int, int], float] = {}

    for (product_id, warehouse_key), snapshots in sorted(grouped.items()):
        product = products.get(product_id)
        warehouse = warehouses.get(warehouse_key)
        if product is None or warehouse is None:
            continue

        cache_key = (product_id, warehouse_key)
        if cache_key not in demand_cache:
            demand, _, _ = _demand_for(
                db, product_id, anchor, warehouse_id=warehouse_key
            )
            demand_cache[cache_key] = demand
        weekly_demand = demand_cache[cache_key]

        # 기한이 이른 순서 = 나가는 순서. 기한 없는 로트는 맨 뒤로 보낸다.
        ordered = sorted(
            snapshots,
            key=lambda s: (s.expiry_date is None, s.expiry_date or date.max),
        )

        ahead = 0
        for snapshot in ordered:
            days_remaining = (
                (snapshot.expiry_date - reference).days if snapshot.expiry_date else None
            )
            weeks_to_clear = forecasting.weeks_of_supply(
                ahead + snapshot.qty, weekly_demand
            )

            # 이미 지난 기한은 소진율과 무관하게 위험이다.
            expired = days_remaining is not None and days_remaining <= 0

            # 소진 이력이 없으면(주간수요 0) 언제 빠질지 알 수 없다. 용인
            # 메인창고처럼 판매 채널이 붙지 않은 거점이 여기 해당한다 — 이관으로
            # 나가지만 그 이동이 아직 주차 집계에 잡히지 않는다. 근거 없이
            # 위험으로 칠하면 화면이 전부 빨개져 진짜 위험이 묻힌다.
            judgeable = days_remaining is not None and weekly_demand > 0
            at_risk = expired or (
                judgeable and weeks_to_clear * 7 > days_remaining
            )

            if not at_risk_only or at_risk:
                lots.append(
                    ExpiryLot(
                        product_id=product_id,
                        product_code=product.product_code,
                        product_name=product.name,
                        brand_category=product.brand.category,
                        warehouse_id=warehouse_key,
                        warehouse_name=warehouse.name,
                        expiry_date=snapshot.expiry_date,
                        qty=snapshot.qty,
                        qty_ahead=ahead,
                        days_remaining=days_remaining,
                        weeks_to_clear=weeks_to_clear,
                        is_at_risk=at_risk,
                        is_judgeable=judgeable or expired,
                    )
                )
            ahead += snapshot.qty

    return lots


# ══════════════════════════════════════════════════════════════════════
# 이관 시뮬레이션
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TransferSuggestion:
    product_id: int
    product_code: str
    product_name: str
    from_warehouse_id: int
    from_warehouse_name: str
    to_warehouse_id: int
    to_warehouse_name: str
    #: 도착지의 현재 재고와 소진 속도
    current_qty: int
    weekly_demand: float
    weeks_of_supply: float
    shortage_qty: int
    #: MOQ 배수로 올린 실제 이관 제안 수량
    suggested_qty: int
    moq: int
    #: HUB 재고가 모자라 제안이 깎였는가
    limited_by_hub: bool
    cost: Decimal | None


@dataclass(frozen=True, slots=True)
class TransferPlan:
    hub_warehouse_id: int | None
    suggestions: list[TransferSuggestion] = field(default_factory=list)
    #: HUB 재고가 부족해 채우지 못한 품목
    shortfalls: list[str] = field(default_factory=list)

    @property
    def total_qty(self) -> int:
        return sum(suggestion.suggested_qty for suggestion in self.suggestions)


def simulate_transfers(
    db: Session,
    *,
    as_of: date | None = None,
    target_weeks: float = TRANSFER_TARGET_WEEKS,
) -> TransferPlan:
    """용인 메인창고(HUB) → 각 풀필먼트 창고 이관 제안.

    거점별로 `목표주수 × 주간수요` 에 못 미치는 만큼을 채운다. HUB 재고를
    넘겨 배분하지 않으며, 모자라면 **재고일수가 급한 곳부터** 준다.
    """
    reference = as_of or date.today()

    hub = db.scalar(select(Warehouse).where(Warehouse.type == WarehouseType.HUB))
    if hub is None:
        logger.warning("HUB 창고가 없습니다. 이관 제안을 만들 수 없습니다.")
        return TransferPlan(hub_warehouse_id=None)

    positions = stock_summary(db, as_of=reference, by_warehouse=True, include_empty=True)
    hub_stock = {
        position.product_id: position.qty
        for position in positions
        if position.warehouse_id == hub.id
    }

    moq_overrides = {
        (moq.warehouse_id, moq.product_id): moq.transfer_moq
        for moq in db.scalars(select(WarehouseProductMoq))
    }
    warehouses = {w.id: w for w in db.scalars(select(Warehouse))}
    costs = _logistics_costs(db, hub.id)

    # 급한 곳부터 배분한다. 재고일수가 낮을수록 먼저.
    candidates = sorted(
        (
            position
            for position in positions
            if position.warehouse_id not in (None, hub.id)
            and warehouses.get(position.warehouse_id, hub).is_active
        ),
        key=lambda position: position.weeks_of_supply,
    )

    suggestions: list[TransferSuggestion] = []
    shortfalls: list[str] = []
    remaining = dict(hub_stock)

    for position in candidates:
        if position.weekly_demand <= 0:
            continue  # 소진되지 않는 거점에는 보내지 않는다

        target_qty = position.weekly_demand * target_weeks
        shortage = target_qty - position.qty
        if shortage <= 0:
            continue

        warehouse = warehouses[position.warehouse_id]
        moq = moq_overrides.get(
            (position.warehouse_id, position.product_id), warehouse.default_transfer_moq
        )
        # MOQ 가 없으면 부족분 그대로 올림한다.
        wanted = (
            forecasting.round_up_to_moq(shortage, moq) if moq > 0 else math.ceil(shortage)
        )

        available = remaining.get(position.product_id, 0)
        if available <= 0:
            shortfalls.append(f"{position.product_code} → {warehouse.name}")
            continue

        granted = min(wanted, available)
        limited = granted < wanted
        if limited:
            shortfalls.append(f"{position.product_code} → {warehouse.name}")

        remaining[position.product_id] = available - granted

        suggestions.append(
            TransferSuggestion(
                product_id=position.product_id,
                product_code=position.product_code,
                product_name=position.product_name,
                from_warehouse_id=hub.id,
                from_warehouse_name=hub.name,
                to_warehouse_id=warehouse.id,
                to_warehouse_name=warehouse.name,
                current_qty=position.qty,
                weekly_demand=position.weekly_demand,
                weeks_of_supply=position.weeks_of_supply,
                shortage_qty=math.ceil(shortage),
                suggested_qty=granted,
                moq=moq,
                limited_by_hub=limited,
                cost=_transfer_cost(costs, warehouse.id, granted, position.product_id, db),
            )
        )

    return TransferPlan(
        hub_warehouse_id=hub.id, suggestions=suggestions, shortfalls=shortfalls
    )


def _logistics_costs(db: Session, departure_id: int) -> dict[int, Decimal]:
    from app.models.master import LogisticsCost

    return {
        cost.arrival_warehouse_id: cost.cost_per_tu
        for cost in db.scalars(
            select(LogisticsCost).where(
                LogisticsCost.departure_warehouse_id == departure_id
            )
        )
    }


def _transfer_cost(
    costs: dict[int, Decimal],
    arrival_id: int,
    qty: int,
    product_id: int,
    db: Session,
) -> Decimal | None:
    """구간 비용 × 카툰 수. 구간이 등록되지 않았으면 None (화면은 '-')."""
    per_tu = costs.get(arrival_id)
    if per_tu is None:
        return None

    product = db.get(Product, product_id)
    pack = product.pack_qty_per_tu if product else 1
    cartons = math.ceil(qty / pack) if pack > 0 else qty
    return per_tu * cartons
