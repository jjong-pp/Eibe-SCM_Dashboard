"""
수요 예측 · 발주 시뮬레이션.

원칙 (구 프로젝트에서 이어받음):
  - 머신러닝을 쓰지 않는다. 사칙연산 기반의 통계적 평탄화만 사용한다.
  - 예측 근거가 항상 드러나야 한다. 실무자가 숫자를 따라갈 수 있어야 한다.

이 모듈은 **DB 를 모른다.** 순수 함수만 두어 단위 테스트가 가능하고,
데이터 출처가 바뀌어도 계산 로직은 그대로 쓸 수 있다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

# 발주 규칙: 리드타임을 고려해 6개월(약 24주) 뒤 도착분을 주문한다.
DEFAULT_HORIZON_WEEKS = 24

# 평탄화 상수를 뽑을 때 참조하는 과거 구간.
SMOOTHING_WINDOW_WEEKS = 12

# 목표 안전재고 — 시뮬레이션 종료 시점에 이만큼은 남아 있어야 한다.
DEFAULT_SAFETY_STOCK_WEEKS = 6

# 비상 항공 전환을 검토하는 시점.
AIR_SHIPMENT_CHECK_WEEK = 12


class StockRisk(StrEnum):
    """재고일수 구간. 적정은 13주(약 3개월) 기준이다.

    CSS 클래스명과 값을 일치시켜 화면에서 그대로 쓴다.
    """

    HIGH = "risk-high"   # < 6주   위험 — 품절 임박
    MID = "risk-mid"     # 6~9주   주의 — 발주 검토
    LOW = "risk-low"     # 9~13주  양호 — 적정
    SAFE = "risk-safe"   # > 13주  과잉 — 이관/할인 검토


#: 구간 경계 (주). 화면 범례와 이 값이 어긋나면 안 되므로 여기서만 정의한다.
RISK_THRESHOLDS_WEEKS = (6.0, 9.0, 13.0)


def classify_stock_risk(weeks_of_supply: float | None) -> StockRisk:
    """재고일수를 위험 구간으로 분류한다.

    소진율이 0이면 재고일수가 무한대이므로 '과잉'으로 본다.
    """
    if weeks_of_supply is None or math.isinf(weeks_of_supply):
        return StockRisk.SAFE

    low, mid, high = RISK_THRESHOLDS_WEEKS
    if weeks_of_supply < low:
        return StockRisk.HIGH
    if weeks_of_supply < mid:
        return StockRisk.MID
    if weeks_of_supply < high:
        return StockRisk.LOW
    return StockRisk.SAFE


def weeks_of_supply(current_stock: int, weekly_demand: float) -> float:
    """현재 재고가 몇 주를 버티는가.

    소진율이 0이면 무한대를 돌려준다. 0으로 나누어 예외를 던지는 대신
    호출부가 그대로 '소진 불가'로 표시할 수 있게 한다.
    """
    if weekly_demand <= 0:
        return math.inf
    return current_stock / weekly_demand


def calc_smoothing_constant(
    outflow_history: list[int], window: int = SMOOTHING_WINDOW_WEEKS
) -> float:
    """주차별 기준 출고량 평균.

    최근 구간의 단순 평균으로 일시적 스파이크를 눌러 안정적인 소진율을 얻는다.
    구간보다 데이터가 적으면 있는 만큼만 쓴다 — 0을 채워 넣으면 신규 품목의
    수요를 실제보다 낮게 잡게 된다.
    """
    if not outflow_history:
        return 0.0

    recent = outflow_history[-window:]
    return sum(recent) / len(recent)


def calc_loss_buffer(
    outflow_history: list[int],
    sales_history: list[int],
    window: int = SMOOTHING_WINDOW_WEEKS,
) -> float:
    """동적 감모 버퍼 — 판매로 설명되지 않는 주당 감소분.

    파손·분실·미기록 이관 등이 여기에 잡힌다. 두 리스트를 **뒤에서부터**
    맞춰 같은 주끼리 비교한다 (길이가 다를 수 있다).
    """
    if not outflow_history or not sales_history:
        return 0.0

    weeks = min(len(outflow_history), len(sales_history), window)
    recent_outflow = outflow_history[-weeks:]
    recent_sales = sales_history[-weeks:]

    return sum(o - s for o, s in zip(recent_outflow, recent_sales, strict=True)) / weeks


@dataclass(frozen=True, slots=True)
class WeekProjection:
    """한 주의 예상 재고 흐름."""

    week: int
    beginning_stock: float
    inbound_qty: int
    demand: float
    ending_stock: float

    @property
    def is_stockout(self) -> bool:
        return self.ending_stock < 0


@dataclass(frozen=True, slots=True)
class SimulationResult:
    current_stock: int
    weekly_demand: float
    smoothing_constant: float
    loss_buffer: float
    projections: list[WeekProjection] = field(default_factory=list)

    @property
    def final_stock(self) -> float:
        return self.projections[-1].ending_stock if self.projections else self.current_stock

    @property
    def first_stockout_week(self) -> int | None:
        """재고가 처음 마이너스가 되는 주. 없으면 None."""
        for projection in self.projections:
            if projection.is_stockout:
                return projection.week
        return None

    @property
    def weeks_of_supply(self) -> float:
        return weeks_of_supply(self.current_stock, self.weekly_demand)

    @property
    def risk(self) -> StockRisk:
        return classify_stock_risk(self.weeks_of_supply)


def simulate_inventory(
    current_stock: int,
    smoothing_constant: float,
    loss_buffer: float,
    scheduled_inbounds: dict[int, int] | None = None,
    weight_factor: float = 1.0,
    horizon: int = DEFAULT_HORIZON_WEEKS,
) -> SimulationResult:
    """미래 재고 추이 시뮬레이션.

        기말재고(W) = 기말재고(W-1) + 입고예정(W) - 주간수요

    주간수요는 `평탄화상수 × 가중치 + 감모버퍼` 다. 가중치는 실무자가 조정하는
    수요 배수이며 **감모 버퍼에는 곱하지 않는다** — 감모는 판매량과 무관하게
    발생하는 고정 손실로 보기 때문이다.

    Args:
        scheduled_inbounds: {주차번호: 수량}. 주차는 1부터 센다.
        weight_factor: 수요 가중치. 1.0 이 기준.
    """
    inbounds = scheduled_inbounds or {}
    weekly_demand = smoothing_constant * weight_factor + loss_buffer

    projections: list[WeekProjection] = []
    stock: float = current_stock

    for week in range(1, horizon + 1):
        inbound = inbounds.get(week, 0)
        beginning = stock
        ending = beginning + inbound - weekly_demand

        projections.append(
            WeekProjection(
                week=week,
                beginning_stock=round(beginning, 1),
                inbound_qty=inbound,
                demand=round(weekly_demand, 1),
                ending_stock=round(ending, 1),
            )
        )
        stock = ending

    return SimulationResult(
        current_stock=current_stock,
        weekly_demand=round(weekly_demand, 1),
        smoothing_constant=round(smoothing_constant, 1),
        loss_buffer=round(loss_buffer, 2),
        projections=projections,
    )


def round_up_to_moq(shortage: float, moq: int) -> int:
    """부족분을 최소 발주 단위의 배수로 올림한다."""
    if shortage <= 0 or moq <= 0:
        return 0
    return math.ceil(shortage / moq) * moq


def suggest_order_qty(
    simulation: SimulationResult,
    moq: int,
    safety_stock_weeks: float = DEFAULT_SAFETY_STOCK_WEEKS,
) -> int:
    """제안 발주 수량.

    시뮬레이션 종료 시점에 `안전재고 주수 × 주간수요` 만큼 남기는 것을 목표로
    부족분을 계산하고, MOQ 배수로 올린다.
    """
    target = simulation.weekly_demand * safety_stock_weeks
    shortage = target - simulation.final_stock
    return round_up_to_moq(shortage, moq)


@dataclass(frozen=True, slots=True)
class AirShipmentAlert:
    week: int
    shortage_qty: float
    message: str


def check_air_shipment(
    simulation: SimulationResult, check_week: int = AIR_SHIPMENT_CHECK_WEEK
) -> AirShipmentAlert | None:
    """비상 항공 전환 검토 알림.

    해상 운송 리드타임 안에 재고가 바닥나면 항공으로 전환해야 한다.
    지정 주차 시점의 재고가 마이너스면 알린다.
    """
    if len(simulation.projections) < check_week:
        return None

    projection = simulation.projections[check_week - 1]
    if not projection.is_stockout:
        return None

    shortage = abs(projection.ending_stock)
    return AirShipmentAlert(
        week=check_week,
        shortage_qty=shortage,
        message=(
            f"{check_week}주 뒤 예상 재고 부족 {shortage:,.0f}개. "
            f"항공 전환 시 약 2주 만에 긴급 입고가 가능합니다."
        ),
    )
