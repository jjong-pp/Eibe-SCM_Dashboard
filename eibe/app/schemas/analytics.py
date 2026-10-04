"""
매출 대시보드 스키마.

서비스가 돌려주는 dataclass 를 그대로 내보내지 않는다. 화면이 의존하는 계약을
여기 고정해 두면 내부 계산 구조를 바꿔도 프론트가 깨지지 않는다.

**문구를 만들지 않는다.** 구 버전은 알림 텍스트에 `<strong>` 을 박아 보냈고,
그 문자열이 그대로 innerHTML 에 들어갔다. 여기서는 사실만 담고 화면이 문장을
조립한다 (D15).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class PeriodResponse(BaseModel):
    start: date
    end: date
    days: int


class TotalsResponse(BaseModel):
    qty: int
    amount: Decimal


class ComparisonResponse(BaseModel):
    period: PeriodResponse
    previous_period: PeriodResponse
    current: TotalsResponse
    previous: TotalsResponse
    qty_pct: float
    amount_pct: float


class MomentumResponse(BaseModel):
    """금주가 직전 4주 평균에서 얼마나 벗어났는가."""

    avg_qty: float
    avg_amount: Decimal
    qty_diff: float
    amount_diff: Decimal
    qty_pct: float
    amount_pct: float


class KpiResponse(BaseModel):
    week: ComparisonResponse
    month: ComparisonResponse
    momentum: MomentumResponse
    #: `Jun-W3` 형식 (영문 3글자, 한글 주차 표기 금지)
    week_label: str
    month_label: str


class ChannelMixResponse(BaseModel):
    channel_group: str
    qty: int
    amount: Decimal
    share_pct: float
    #: 점유율 변화는 **%p** 다. 증감률과 섞으면 안 된다.
    share_wow_pp: float
    share_mom_pp: float
    qty_wow_pct: float


class PortfolioRowResponse(BaseModel):
    lineup: str
    qty: int
    amount: Decimal
    #: null = 직전 구간 실적이 없어 증감률을 낼 수 없다 (신규)
    qty_pct: float | None
    is_new: bool


class PortfolioResponse(BaseModel):
    growth: list[PortfolioRowResponse]
    decline: list[PortfolioRowResponse]


class AlertResponse(BaseModel):
    kind: str      # up / down
    scope: str     # product / channel
    name: str
    change_pct: float
    #: 같은 주에 걸친 행사명. 비어 있으면 행사로 설명되지 않는 변화다.
    related_events: list[str]


class PromotionEffectResponse(BaseModel):
    event_name: str
    channel_name: str
    channel_group: str
    lineup: str | None
    period: PeriodResponse
    qty: int
    amount: Decimal
    elapsed_days: int
    baseline_daily_qty: float
    event_daily_qty: float
    #: null = 기준선(직전 14일 판매)이 없거나 아직 시작 전
    lift_pct: float | None
    overlaps_week: bool
    is_upcoming: bool
    is_schedule_only: bool


class TrendSeriesResponse(BaseModel):
    label: str
    total: Decimal
    data: list[Decimal]


class TrendResponse(BaseModel):
    labels: list[str]
    series: list[TrendSeriesResponse]
    unit: str
    value: str
    basis: str
    #: 계열이 상한을 넘어 '기타(나머지)'로 합쳐졌는가
    truncated: bool


class DashboardMetaResponse(BaseModel):
    reference_date: date
    week_key: str
    month_key: str
    anchor: str
    full_period: bool
    row_count: int
    week_keys: list[str]
    month_keys: list[str]
    categories: list[str]
    category: str | None


class DashboardResponse(BaseModel):
    brand_id: int | None
    kpi: KpiResponse
    channel_mix: list[ChannelMixResponse]
    portfolio: PortfolioResponse
    alerts: list[AlertResponse]
    promotions: list[PromotionEffectResponse]
    trend: TrendResponse
    meta: DashboardMetaResponse
