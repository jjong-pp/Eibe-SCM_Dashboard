"""
매출 분석 — Sales Hub 대시보드 지표.

구 `sales code/domain/analytics.js` (1,074줄) 포팅. 계산 규칙은 그대로 옮기되
네 가지를 의도적으로 바꿨다.

1. **입력이 시트 배열이 아니라 정규화된 판매 원장이다.** 채널 그룹과 라인업이
   DB 매핑으로 확정되므로 구 버전의 접두어 추측 매칭(`resolveGroup` 의
   `startsWith` 루프)은 필요 없다. 매핑이 없는 건은 추측하지 않고 '기타'로
   모은 뒤 `derive.unmapped_sources()` 로 드러낸다.

2. **출력에 HTML 을 넣지 않는다.** 구 버전은 알림 문구에 `<strong>` 을 박아
   보냈다. 서비스 계층이 표현을 정하면 재사용이 막히고, 그 문자열을 그대로
   innerHTML 에 꽂으면 업로드된 제품명이 스크립트가 된다.

3. **주간 비교를 같은 경과일수끼리 한다.** `Periods` 참조.

4. **'기준선 없음'을 큰 수로 표현하지 않는다.** 구 버전은 직전 판매가 0일 때
   리프트를 `99999` 로 채웠다. 여기서는 `None` 이며, 화면이 `-` 로 그린다.

머신러닝은 쓰지 않는다 — 합계와 사칙연산뿐이라 모든 숫자를 손으로 따라갈 수 있다.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dates import (
    IsoWeek,
    add_months,
    iso_week_of,
    month_end,
    month_key,
    month_start,
)
from app.models.master import Channel, Product, ProductAlias
from app.models.sales import Promotion, SalesOrder

logger = logging.getLogger(__name__)

# ── 임계값 ────────────────────────────────────────────────────────────
# 구 `SheetSchema.ANALYTICS_THRESHOLDS` 에서 옮겨왔다. 화면 문구가 이 값을
# 설명하므로(예: "전주 대비 50% 이상 증가") 한 곳에서만 정의한다.
MIN_QTY_PORTFOLIO = 1
ALERT_PRODUCT_UP_PCT = 50.0
ALERT_PRODUCT_DOWN_PCT = -25.0
ALERT_CHANNEL_DOWN_PCT = -20.0
# 채널 상승은 두 단계다: 행사가 걸려 있으면 30%, 없으면 50% 부터 알린다.
ALERT_CHANNEL_UP_PCT = 30.0
ALERT_CHANNEL_UP_SOLO_PCT = 50.0
ALERT_MAX = 5

#: 포트폴리오 상승·하락에 각각 보여줄 개수.
PORTFOLIO_TOP_N = 3

#: 행사 효과를 재는 기준선 구간 (행사 시작 직전 며칠).
PROMO_BASELINE_DAYS = 14

#: 모멘텀 기준 — 직전 몇 개의 '완결된' 주를 평균할 것인가.
MOMENTUM_WEEKS = 4

#: 추이 계열 상한. 이보다 많으면 나머지를 하나로 합친다 — 범례가 화면을 덮는다.
TREND_SERIES_CAP = 120

#: 매핑되지 않은 채널이 모이는 그룹명.
UNASSIGNED_GROUP = "기타"

#: 라인업을 알 수 없는 판매 건.
UNASSIGNED_LINEUP = "(미지정)"


# ══════════════════════════════════════════════════════════════════════
# 기간
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Period:
    start: date
    end: date

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def __str__(self) -> str:
        return f"{self.start.isoformat()}~{self.end.isoformat()}"


@dataclass(frozen=True, slots=True)
class Anchor:
    """조회 기준 시점.

    `full_period` 는 '구간 전체를 본다'는 뜻이다. 지난 달을 지정해 놓고
    오늘 날짜에서 잘라 보여주면 안 되기 때문에 구분한다.
    """

    reference: date
    full_period: bool
    raw: str


def resolve_anchor(value: str | None = None, *, today: date | None = None) -> Anchor:
    """조회 기준을 해석한다.

    받는 형식 (구 버전의 `resolveAnchor` 와 같은 역할):
        ``week:2026-W25``   그 주 일요일 기준, 구간 전체
        ``month:2026-06``   그 달 말일 기준, 구간 전체
        ``2026-06-19``      그 날짜까지 (진행 중 구간)
        생략/해석 불가       오늘까지

    주차·월 키 형식은 `IsoWeek.key` · `month_key()` 가 내보내는 것과 맞춘다.
    구 프론트가 쓰던 `2026-M06` 은 우리가 어디서도 만들지 않는 형식이라 받지 않는다.
    """
    reference = today or date.today()
    raw = (value or "").strip()
    if not raw:
        return Anchor(reference, full_period=False, raw="")

    if raw.startswith("week:"):
        parsed = _parse_week_key(raw[5:])
        if parsed is not None:
            return Anchor(parsed.end_date(), full_period=True, raw=raw)

    elif raw.startswith("month:"):
        parsed_month = _parse_month_key(raw[6:])
        if parsed_month is not None:
            return Anchor(month_end(parsed_month), full_period=True, raw=raw)

    else:
        try:
            return Anchor(date.fromisoformat(raw), full_period=False, raw=raw)
        except ValueError:
            pass

    logger.warning("해석할 수 없는 조회 기준: %r — 오늘 기준으로 대체합니다.", raw)
    return Anchor(reference, full_period=False, raw="")


def _parse_week_key(value: str) -> IsoWeek | None:
    """`2026-W25` → IsoWeek. 실재하지 않는 주차(53주가 없는 해)는 None."""
    year_part, sep, week_part = value.partition("-W")
    if not sep:
        return None
    try:
        week = IsoWeek(int(year_part), int(week_part))
        week.start_date()  # 53주가 없는 해면 여기서 걸린다
    except ValueError:
        return None
    return week


def _parse_month_key(value: str) -> date | None:
    """`2026-06` → 그 달 1일."""
    year_part, sep, month_part = value.partition("-")
    if not sep:
        return None
    try:
        return date(int(year_part), int(month_part), 1)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class Periods:
    """비교에 쓰는 네 구간.

    **직전 주를 경과일수만큼만 잘라 비교한다.** 구 버전은 이번 주를 기준일까지
    자르면서(`weekEndClamped`) 직전 주는 일요일까지 통째로 썼다. 수요일에 열면
    3일치와 7일치를 견주게 되어 WoW 가 늘 폭락으로 보인다. 월 비교는 구 버전도
    같은 날짜끼리(`sameDayPrevMonth`) 맞췄으므로, 주 비교를 거기에 맞춘 것이다.
    """

    week: Period
    prev_week: Period
    month: Period
    prev_month: Period
    momentum_weeks: list[Period] = field(default_factory=list)


def build_periods(anchor: Anchor) -> Periods:
    reference = anchor.reference
    iso = iso_week_of(reference)

    week_start = iso.start_date()
    # 진행 중인 주는 기준일에서 끊는다. 아직 오지 않은 날을 0원으로 잡으면 안 된다.
    week_end = min(iso.end_date(), reference)
    elapsed = (week_end - week_start).days

    prev_week_start = week_start - timedelta(days=7)
    prev_week = Period(prev_week_start, prev_week_start + timedelta(days=elapsed))

    m_start = month_start(reference)
    m_end = month_end(reference) if anchor.full_period else reference

    prev_month_ref = add_months(reference, -1)
    prev_m_start = month_start(prev_month_ref)
    # 같은 날짜끼리 비교한다. add_months 가 말일을 클램프하므로 3/31 → 2/28.
    prev_m_end = month_end(prev_month_ref) if anchor.full_period else prev_month_ref

    momentum = []
    for offset in range(1, MOMENTUM_WEEKS + 1):
        start = week_start - timedelta(days=7 * offset)
        momentum.append(Period(start, start + timedelta(days=6)))

    return Periods(
        week=Period(week_start, week_end),
        prev_week=prev_week,
        month=Period(m_start, m_end),
        prev_month=Period(prev_m_start, prev_m_end),
        momentum_weeks=momentum,
    )


# ══════════════════════════════════════════════════════════════════════
# 원장 읽기
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class SalesRow:
    """집계용으로 평탄화한 판매 한 건.

    원장을 한 번만 읽고 이후 계산은 메모리에서 한다. 대시보드 하나가 같은
    데이터를 KPI·믹스·포트폴리오·알림·추이로 예닐곱 번 훑기 때문에, 구간마다
    쿼리를 새로 던지는 것보다 이 편이 단순하고 빠르다.
    """

    ship_date: date
    category: str
    channel_name: str
    channel_group: str
    lineup: str
    product_name: str
    qty: int
    amount: Decimal


def _channel_group_of(channel: Channel | None) -> str:
    """채널이 속한 그룹.

    구 버전은 매핑이 없으면 채널명 접두어로 그룹을 추측했다. 시트 매핑이
    늘 불완전했기 때문인데, 여기서는 매핑이 DB 에 있으므로 추측하지 않는다.
    추측한 집계는 틀려도 드러나지 않는다.
    """
    if channel is None:
        return UNASSIGNED_GROUP
    if channel.channel_group:
        return channel.channel_group
    # 주요 채널은 그 자체가 하나의 그룹이다 (구 `5 채널설정` 시트).
    if channel.is_major:
        return channel.name
    return UNASSIGNED_GROUP


def load_rows(
    db: Session,
    *,
    brand_id: int | None = None,
    category: str | None = None,
) -> list[SalesRow]:
    """판매 원장을 집계용 행으로 읽어온다."""
    channels = {channel.id: channel for channel in db.scalars(select(Channel))}

    # 라인업명은 별칭에 있고, 없으면 품목명을 쓴다. 별칭 자체가 없으면 원본
    # 문자열이 그대로 라인업이 된다 — 매핑 전에도 화면이 비지 않도록.
    lineup_by_source = {
        source: (lineup or product_name)
        for source, lineup, product_name in db.execute(
            select(ProductAlias.source_name, ProductAlias.lineup_name, Product.name).join(
                Product, ProductAlias.product_id == Product.id
            )
        ).all()
    }

    stmt = select(SalesOrder)
    if brand_id is not None:
        stmt = stmt.where(SalesOrder.brand_id == brand_id)
    if category:
        stmt = stmt.where(SalesOrder.category == category)

    rows: list[SalesRow] = []
    for order in db.scalars(stmt):
        channel = channels.get(order.channel_id) if order.channel_id else None
        rows.append(
            SalesRow(
                ship_date=order.ship_date,
                category=order.category or UNASSIGNED_GROUP,
                channel_name=channel.name if channel else order.source_channel_name,
                channel_group=_channel_group_of(channel),
                lineup=lineup_by_source.get(
                    order.source_product_name, order.source_product_name
                )
                or UNASSIGNED_LINEUP,
                product_name=order.source_product_name,
                qty=order.qty,
                amount=order.amount or Decimal("0"),
            )
        )
    return rows


def major_channel_groups(db: Session) -> list[str]:
    """대시보드에 항상 노출할 그룹 (구 `5 채널설정` 시트).

    실적이 0인 주에도 행을 남긴다 — 사라진 채널과 안 팔린 채널은 다르다.
    """
    groups: list[str] = []
    for channel in db.scalars(select(Channel).where(Channel.is_major.is_(True))):
        group = _channel_group_of(channel)
        if group not in groups:
            groups.append(group)
    return groups


# ══════════════════════════════════════════════════════════════════════
# 합계 · 증감
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Totals:
    qty: int = 0
    amount: Decimal = Decimal("0")


def sum_rows(rows: list[SalesRow]) -> Totals:
    return Totals(
        qty=sum(row.qty for row in rows),
        amount=sum((row.amount for row in rows), Decimal("0")),
    )


def rows_in(rows: list[SalesRow], period: Period) -> list[SalesRow]:
    return [row for row in rows if period.contains(row.ship_date)]


def pct_change(current: float | Decimal, previous: float | Decimal) -> float:
    """증감률(%).

    직전 값이 0이면 나눌 수 없다. 구 버전과 같이 현재 값이 있으면 100%,
    없으면 0% 로 본다 — 무한대를 화면까지 흘려보내지 않기 위한 관례다.
    """
    prev = float(previous)
    cur = float(current)
    if prev == 0:
        return 100.0 if cur else 0.0
    return (cur - prev) / prev * 100.0


@dataclass(frozen=True, slots=True)
class Comparison:
    """한 구간과 직전 구간의 대비."""

    period: Period
    previous_period: Period
    current: Totals
    previous: Totals

    @property
    def qty_pct(self) -> float:
        return pct_change(self.current.qty, self.previous.qty)

    @property
    def amount_pct(self) -> float:
        return pct_change(self.current.amount, self.previous.amount)


def compare(rows: list[SalesRow], period: Period, previous: Period) -> Comparison:
    return Comparison(
        period=period,
        previous_period=previous,
        current=sum_rows(rows_in(rows, period)),
        previous=sum_rows(rows_in(rows, previous)),
    )


# ══════════════════════════════════════════════════════════════════════
# KPI
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Momentum:
    """금주가 직전 4주 평균에서 얼마나 벗어났는가.

    전주 한 주만 보면 그 주가 유난히 좋았는지 나빴는지 알 수 없다.
    """

    avg_qty: float
    avg_amount: Decimal
    qty_diff: float
    amount_diff: Decimal
    qty_pct: float
    amount_pct: float


@dataclass(frozen=True, slots=True)
class Kpi:
    week: Comparison
    month: Comparison
    momentum: Momentum
    week_label: str
    month_label: str


def compute_kpi(rows: list[SalesRow], periods: Periods, anchor: Anchor) -> Kpi:
    week = compare(rows, periods.week, periods.prev_week)
    month = compare(rows, periods.month, periods.prev_month)

    weekly = [sum_rows(rows_in(rows, period)) for period in periods.momentum_weeks]
    count = len(weekly) or 1
    avg_qty = sum(total.qty for total in weekly) / count
    avg_amount = sum((total.amount for total in weekly), Decimal("0")) / count

    momentum = Momentum(
        avg_qty=avg_qty,
        avg_amount=avg_amount,
        qty_diff=week.current.qty - avg_qty,
        amount_diff=week.current.amount - avg_amount,
        qty_pct=pct_change(week.current.qty, avg_qty),
        amount_pct=pct_change(week.current.amount, avg_amount),
    )

    iso = iso_week_of(anchor.reference)
    if anchor.full_period:
        month_label = f"{anchor.reference.year}년 {anchor.reference.month}월"
    else:
        month_label = (
            f"{anchor.reference.month}/1~{anchor.reference.day}일"
        )

    return Kpi(
        week=week,
        month=month,
        momentum=momentum,
        week_label=iso.label(),
        month_label=month_label,
    )


# ══════════════════════════════════════════════════════════════════════
# 채널 믹스
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ChannelMixRow:
    """채널 그룹별 비중.

    점유율 변화는 **%p**(퍼센트 포인트)다. 매출이 늘어도 남이 더 늘면
    점유율은 떨어진다 — 증감률과 섞으면 안 되는 값이다.
    """

    channel_group: str
    qty: int
    amount: Decimal
    share_pct: float
    share_wow_pp: float
    share_mom_pp: float
    qty_wow_pct: float


def _by_group(rows: list[SalesRow]) -> dict[str, Totals]:
    buckets: dict[str, list[SalesRow]] = defaultdict(list)
    for row in rows:
        buckets[row.channel_group].append(row)
    return {group: sum_rows(group_rows) for group, group_rows in buckets.items()}


def _share(totals: dict[str, Totals], group: str, denominator: Decimal) -> float:
    if denominator == 0:
        return 0.0
    amount = totals.get(group, Totals()).amount
    return float(amount) / float(denominator) * 100.0


def compute_channel_mix(
    rows: list[SalesRow], periods: Periods, major_groups: list[str]
) -> list[ChannelMixRow]:
    week = _by_group(rows_in(rows, periods.week))
    prev_week = _by_group(rows_in(rows, periods.prev_week))
    month = _by_group(rows_in(rows, periods.month))
    prev_month = _by_group(rows_in(rows, periods.prev_month))

    week_total = sum((t.amount for t in week.values()), Decimal("0"))
    prev_week_total = sum((t.amount for t in prev_week.values()), Decimal("0"))
    month_total = sum((t.amount for t in month.values()), Decimal("0"))
    prev_month_total = sum((t.amount for t in prev_month.values()), Decimal("0"))

    groups = list(major_groups)
    for group in week:
        if group not in groups:
            groups.append(group)

    mix: list[ChannelMixRow] = []
    for group in groups:
        current = week.get(group, Totals())
        if current.amount == 0 and current.qty == 0 and group not in major_groups:
            continue

        mix.append(
            ChannelMixRow(
                channel_group=group,
                qty=current.qty,
                amount=current.amount,
                share_pct=_share(week, group, week_total),
                share_wow_pp=(
                    _share(week, group, week_total)
                    - _share(prev_week, group, prev_week_total)
                ),
                share_mom_pp=(
                    _share(month, group, month_total)
                    - _share(prev_month, group, prev_month_total)
                ),
                qty_wow_pct=pct_change(
                    current.qty, prev_week.get(group, Totals()).qty
                ),
            )
        )

    return sorted(mix, key=lambda row: row.amount, reverse=True)


# ══════════════════════════════════════════════════════════════════════
# 포트폴리오 (라인업 성장 · 하락)
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class PortfolioRow:
    lineup: str
    qty: int
    amount: Decimal
    #: 직전 구간 실적이 없으면 None — 증감률을 낼 수 없다는 뜻이다.
    qty_pct: float | None
    is_new: bool


@dataclass(frozen=True, slots=True)
class Portfolio:
    growth: list[PortfolioRow]
    decline: list[PortfolioRow]


def _by_lineup(rows: list[SalesRow]) -> dict[str, Totals]:
    buckets: dict[str, list[SalesRow]] = defaultdict(list)
    for row in rows:
        buckets[row.lineup or UNASSIGNED_LINEUP].append(row)
    return {lineup: sum_rows(items) for lineup, items in buckets.items()}


def compute_portfolio(
    rows: list[SalesRow], periods: Periods, min_qty: int = MIN_QTY_PORTFOLIO
) -> Portfolio:
    """월 기준 라인업 성장·하락 상위.

    사라진 라인업(직전 달에는 있었으나 이번 달 0)도 -100% 로 넣는다. 목록에서
    조용히 빠지면 '문제 없음'처럼 보인다.
    """
    current = _by_lineup(rows_in(rows, periods.month))
    previous = _by_lineup(rows_in(rows, periods.prev_month))

    ranked: list[PortfolioRow] = []
    for lineup, totals in current.items():
        if totals.qty < min_qty:
            continue
        before = previous.get(lineup)
        is_new = before is None or before.qty == 0
        ranked.append(
            PortfolioRow(
                lineup=lineup,
                qty=totals.qty,
                amount=totals.amount,
                qty_pct=None if is_new else pct_change(totals.qty, before.qty),
                is_new=is_new,
            )
        )

    for lineup, totals in previous.items():
        if lineup not in current and totals.qty >= min_qty:
            ranked.append(
                PortfolioRow(
                    lineup=lineup,
                    qty=0,
                    amount=Decimal("0"),
                    qty_pct=-100.0,
                    is_new=False,
                )
            )

    # 신규는 증감률이 없으므로 맨 앞에 둔다 (구 버전의 `?? 9999` 와 같은 순서).
    growth = sorted(
        (row for row in ranked if row.is_new or (row.qty_pct or 0) > 0),
        key=lambda row: (0 if row.is_new else 1, -(row.qty_pct or 0), -row.qty),
    )[:PORTFOLIO_TOP_N]

    decline = sorted(
        (row for row in ranked if row.qty_pct is not None and row.qty_pct < 0),
        key=lambda row: row.qty_pct or 0,
    )[:PORTFOLIO_TOP_N]

    return Portfolio(growth=growth, decline=decline)


# ══════════════════════════════════════════════════════════════════════
# 행사 효과
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class PromotionEffect:
    """행사 하나의 판매 기여.

    리프트는 **일평균 판매량 배수**다. 행사 기간과 직전 14일의 길이가 다르므로
    총량으로 비교하면 긴 행사가 무조건 이긴다.
    """

    event_name: str
    channel_name: str
    #: 행사 채널이 속한 그룹. 알림을 그룹 단위로 붙일 때 쓴다.
    channel_group: str
    lineup: str | None
    period: Period
    qty: int
    amount: Decimal
    #: 기준일까지 실제로 지난 행사 일수. 아직 시작 전이면 0.
    elapsed_days: int
    baseline_daily_qty: float
    event_daily_qty: float
    #: 기준선이 없거나(직전 14일 판매 0) 아직 시작 전이면 None.
    lift_pct: float | None
    overlaps_week: bool

    @property
    def is_upcoming(self) -> bool:
        """아직 시작하지 않은 행사. 실적이 없는 것이 정상이다."""
        return self.elapsed_days <= 0

    @property
    def is_schedule_only(self) -> bool:
        """시작했는데 실판매가 0인 행사. 미진행이나 집계 누락을 의심한다."""
        return not self.is_upcoming and self.qty == 0


def compute_promotion_effects(
    db: Session,
    rows: list[SalesRow],
    periods: Periods,
    *,
    brand_id: int | None = None,
) -> list[PromotionEffect]:
    stmt = select(Promotion)
    if brand_id is not None:
        stmt = stmt.where(Promotion.brand_id == brand_id)

    group_by_channel = {
        channel.name: _channel_group_of(channel)
        for channel in db.scalars(select(Channel))
    }

    lineup_by_source = {
        source: (lineup or product_name)
        for source, lineup, product_name in db.execute(
            select(ProductAlias.source_name, ProductAlias.lineup_name, Product.name).join(
                Product, ProductAlias.product_id == Product.id
            )
        ).all()
    }

    # '지금'은 조회 기준 주의 끝이다. 과거 주차를 조회하면 그 시점 기준으로
    # 행사 진행률이 계산되어야 한다.
    reference = periods.week.end

    effects: list[PromotionEffect] = []
    for promo in db.scalars(stmt):
        channel_name = (promo.source_channel_name or "").strip()
        event_name = (promo.event_name or "").strip()
        if not channel_name or not event_name:
            # 채널이나 행사명이 없으면 어떤 판매에 붙일지 정할 수 없다.
            continue

        source_product = (promo.source_product_name or "").strip()
        lineup = (
            lineup_by_source.get(source_product, source_product)
            if source_product
            else None
        )

        period = Period(promo.start_date, promo.end_date)
        baseline = Period(
            promo.start_date - timedelta(days=PROMO_BASELINE_DAYS),
            promo.start_date - timedelta(days=1),
        )

        def matches(row: SalesRow) -> bool:
            if lineup and row.lineup != lineup:
                return False
            return channel_name in (row.channel_name, row.channel_group)

        # 조회 기준일까지만 본다. 대시보드 전체가 '그 시점 기준' 화면이므로
        # 행사 실적만 미래까지 앞서 나가면 안 된다. 시작 전이면 0일이고,
        # 리프트를 계산하지 않는다 — 구 버전은 이 경우 -100% 를 내보내
        # 아직 열지도 않은 행사가 실패한 것처럼 보였다.
        elapsed = (min(period.end, reference) - period.start).days + 1
        elapsed_period = Period(period.start, min(period.end, reference))

        during = (
            [row for row in rows if matches(row) and elapsed_period.contains(row.ship_date)]
            if elapsed > 0
            else []
        )
        before = [row for row in rows if matches(row) and baseline.contains(row.ship_date)]

        during_total = sum_rows(during)
        baseline_daily = sum_rows(before).qty / PROMO_BASELINE_DAYS
        # 진행 중인 행사를 전체 기간으로 나누면 일평균이 실제보다 낮게 나온다.
        event_daily = during_total.qty / elapsed if elapsed > 0 else 0.0

        effects.append(
            PromotionEffect(
                event_name=event_name,
                channel_name=channel_name,
                channel_group=group_by_channel.get(channel_name, UNASSIGNED_GROUP),
                lineup=lineup,
                period=period,
                qty=during_total.qty,
                amount=during_total.amount,
                elapsed_days=max(elapsed, 0),
                baseline_daily_qty=baseline_daily,
                event_daily_qty=event_daily,
                lift_pct=(
                    (event_daily / baseline_daily - 1) * 100.0
                    if baseline_daily > 0 and elapsed > 0
                    else None
                ),
                overlaps_week=(
                    promo.start_date <= periods.week.end
                    and promo.end_date >= periods.week.start
                ),
            )
        )

    return sorted(effects, key=lambda e: e.period.start, reverse=True)


# ══════════════════════════════════════════════════════════════════════
# 알림
# ══════════════════════════════════════════════════════════════════════


class AlertKind(StrEnum):
    UP = "up"
    DOWN = "down"


class AlertScope(StrEnum):
    PRODUCT = "product"
    CHANNEL = "channel"


@dataclass(frozen=True, slots=True)
class Alert:
    """임계값을 넘은 변화 하나.

    문구를 만들지 않고 사실만 담는다 — 화면이 문장을 조립한다.
    """

    kind: AlertKind
    scope: AlertScope
    name: str
    change_pct: float
    #: 같은 주에 걸쳐 있는 행사명. 비어 있으면 행사로 설명되지 않는 변화다.
    related_events: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.scope.value}:{self.name}"


def compute_alerts(
    rows: list[SalesRow],
    periods: Periods,
    promotions: list[PromotionEffect],
) -> list[Alert]:
    """전주 대비 급변한 라인업·채널을 골라낸다.

    직전 주 실적이 0인 대상은 건너뛴다. 0에서 늘어난 것은 늘 100% 라
    임계값이 의미를 잃는다.
    """
    week_rows = rows_in(rows, periods.week)
    prev_rows = rows_in(rows, periods.prev_week)

    week_events = [effect for effect in promotions if effect.overlaps_week]

    def events_for_lineup(name: str) -> tuple[str, ...]:
        return tuple(
            effect.event_name
            for effect in week_events
            if effect.lineup is None or effect.lineup == name
        )

    def events_for_group(group: str) -> tuple[str, ...]:
        return tuple(
            effect.event_name
            for effect in week_events
            if group in (effect.channel_name, effect.channel_group)
        )

    alerts: list[Alert] = []

    current = _by_lineup(week_rows)
    previous = _by_lineup(prev_rows)
    for lineup, totals in current.items():
        before = previous.get(lineup)
        if before is None or before.qty <= 0:
            continue
        change = pct_change(totals.qty, before.qty)
        if change >= ALERT_PRODUCT_UP_PCT:
            kind = AlertKind.UP
        elif change <= ALERT_PRODUCT_DOWN_PCT:
            kind = AlertKind.DOWN
        else:
            continue
        alerts.append(
            Alert(
                kind=kind,
                scope=AlertScope.PRODUCT,
                name=lineup,
                change_pct=change,
                related_events=events_for_lineup(lineup),
            )
        )

    current_groups = _by_group(week_rows)
    previous_groups = _by_group(prev_rows)
    for group, totals in current_groups.items():
        before = previous_groups.get(group)
        if before is None or before.qty <= 0:
            continue
        change = pct_change(totals.qty, before.qty)
        events = events_for_group(group)

        if change <= ALERT_CHANNEL_DOWN_PCT:
            alerts.append(
                Alert(
                    kind=AlertKind.DOWN,
                    scope=AlertScope.CHANNEL,
                    name=group,
                    change_pct=change,
                    related_events=events,
                )
            )
        elif change >= ALERT_CHANNEL_UP_PCT and (
            events or change >= ALERT_CHANNEL_UP_SOLO_PCT
        ):
            alerts.append(
                Alert(
                    kind=AlertKind.UP,
                    scope=AlertScope.CHANNEL,
                    name=group,
                    change_pct=change,
                    related_events=events,
                )
            )

    # 변화가 큰 순으로 자른다. 다섯 개를 넘기면 아무도 읽지 않는다.
    alerts.sort(key=lambda alert: abs(alert.change_pct), reverse=True)
    return alerts[:ALERT_MAX]


# ══════════════════════════════════════════════════════════════════════
# 추이
# ══════════════════════════════════════════════════════════════════════


class TrendUnit(StrEnum):
    WEEK = "week"
    MONTH = "month"


class TrendValue(StrEnum):
    QTY = "qty"
    AMOUNT = "amount"


class TrendBasis(StrEnum):
    """무엇으로 나눠 볼 것인가."""

    CHANNEL_GROUP = "channel_group"
    CHANNEL = "channel"
    LINEUP = "lineup"
    PRODUCT = "product"
    CATEGORY = "category"


_TREND_ATTR = {
    TrendBasis.CHANNEL_GROUP: "channel_group",
    TrendBasis.CHANNEL: "channel_name",
    TrendBasis.LINEUP: "lineup",
    TrendBasis.PRODUCT: "product_name",
    TrendBasis.CATEGORY: "category",
}

#: 화면이 제공하는 구간 길이. 그 밖의 값은 12로 떨어뜨린다.
TREND_RANGES = (4, 6, 8, 12)
TREND_DEFAULT_RANGE = 12


@dataclass(frozen=True, slots=True)
class TrendSeries:
    label: str
    total: Decimal
    data: list[Decimal]


@dataclass(frozen=True, slots=True)
class Trend:
    labels: list[str]
    series: list[TrendSeries]
    unit: TrendUnit
    value: TrendValue
    basis: TrendBasis
    #: 계열이 상한을 넘어 '기타(나머지)'로 합쳐졌는가.
    truncated: bool


def compute_trend(
    rows: list[SalesRow],
    anchor: Anchor,
    *,
    unit: TrendUnit = TrendUnit.WEEK,
    value: TrendValue = TrendValue.AMOUNT,
    basis: TrendBasis = TrendBasis.CHANNEL_GROUP,
    span: int = TREND_DEFAULT_RANGE,
) -> Trend:
    """기간별 계열 추이.

    기준일 이후 구간은 만들지 않는다 — 아직 오지 않은 주가 0으로 그려지면
    그래프가 절벽처럼 보인다.
    """
    if span not in TREND_RANGES:
        span = TREND_DEFAULT_RANGE

    reference = anchor.reference
    if unit is TrendUnit.WEEK:
        anchor_week = iso_week_of(reference)
        keys = [anchor_week.shift(-offset).key for offset in range(span - 1, -1, -1)]
        labels = [
            anchor_week.shift(-offset).label() for offset in range(span - 1, -1, -1)
        ]

        def key_of(row: SalesRow) -> str:
            return iso_week_of(row.ship_date).key
    else:
        months = [add_months(month_start(reference), -offset) for offset in range(span - 1, -1, -1)]
        keys = [month_key(m) for m in months]
        labels = [f"{m.year}.{m.month}" for m in months]

        def key_of(row: SalesRow) -> str:
            return month_key(row.ship_date)

    attr = _TREND_ATTR[basis]
    wanted = set(keys)
    totals: dict[str, Decimal] = defaultdict(Decimal)
    buckets: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))

    for row in rows:
        key = key_of(row)
        if key not in wanted:
            continue
        label = getattr(row, attr) or UNASSIGNED_GROUP
        amount = Decimal(row.qty) if value is TrendValue.QTY else row.amount
        totals[label] += amount
        buckets[label][key] += amount

    ordered = sorted(totals, key=lambda label: (-totals[label], label))

    truncated = len(ordered) > TREND_SERIES_CAP
    if truncated:
        head = ordered[: TREND_SERIES_CAP - 1]
        rest = ordered[TREND_SERIES_CAP - 1 :]
        rest_label = "기타(나머지)"
        for label in rest:
            totals[rest_label] += totals[label]
            for key, amount in buckets[label].items():
                buckets[rest_label][key] += amount
        ordered = [*head, rest_label]

    return Trend(
        labels=labels,
        series=[
            TrendSeries(
                label=label,
                total=totals[label],
                data=[buckets[label].get(key, Decimal("0")) for key in keys],
            )
            for label in ordered
        ],
        unit=unit,
        value=value,
        basis=basis,
        truncated=truncated,
    )


# ══════════════════════════════════════════════════════════════════════
# 대시보드
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class DashboardMeta:
    reference_date: date
    week_key: str
    month_key: str
    anchor: str
    full_period: bool
    row_count: int
    #: 조회 가능한 주차·월 (최신순). 화면의 기간 선택기가 쓴다.
    week_keys: list[str]
    month_keys: list[str]
    categories: list[str]
    category: str | None


@dataclass(frozen=True, slots=True)
class Dashboard:
    brand_id: int | None
    kpi: Kpi
    channel_mix: list[ChannelMixRow]
    portfolio: Portfolio
    alerts: list[Alert]
    promotions: list[PromotionEffect]
    trend: Trend
    meta: DashboardMeta


def compute_dashboard(
    db: Session,
    *,
    brand_id: int | None = None,
    anchor: str | None = None,
    category: str | None = None,
    today: date | None = None,
    trend_unit: TrendUnit = TrendUnit.WEEK,
    trend_value: TrendValue = TrendValue.AMOUNT,
    trend_basis: TrendBasis = TrendBasis.CHANNEL_GROUP,
    trend_span: int = TREND_DEFAULT_RANGE,
) -> Dashboard:
    """대시보드 한 화면을 한 번에 계산한다.

    원장은 한 번만 읽는다. 카테고리 필터는 지표에만 걸고, 선택기에 쓸
    카테고리 목록은 필터 이전 전체에서 뽑는다 — 한 번 고르면 다른 카테고리로
    옮겨갈 수 없게 되는 것을 막기 위해서다.
    """
    resolved = resolve_anchor(anchor, today=today)
    periods = build_periods(resolved)

    all_rows = load_rows(db, brand_id=brand_id)
    rows = [row for row in all_rows if row.category == category] if category else all_rows

    promotions = compute_promotion_effects(db, rows, periods, brand_id=brand_id)
    groups = major_channel_groups(db)

    return Dashboard(
        brand_id=brand_id,
        kpi=compute_kpi(rows, periods, resolved),
        channel_mix=compute_channel_mix(rows, periods, groups),
        portfolio=compute_portfolio(rows, periods),
        alerts=compute_alerts(rows, periods, promotions),
        promotions=promotions,
        trend=compute_trend(
            rows,
            resolved,
            unit=trend_unit,
            value=trend_value,
            basis=trend_basis,
            span=trend_span,
        ),
        meta=DashboardMeta(
            reference_date=resolved.reference,
            week_key=iso_week_of(resolved.reference).key,
            month_key=month_key(resolved.reference),
            anchor=resolved.raw,
            full_period=resolved.full_period,
            row_count=len(rows),
            week_keys=sorted(
                {iso_week_of(row.ship_date).key for row in all_rows}, reverse=True
            ),
            month_keys=sorted(
                {month_key(row.ship_date) for row in all_rows}, reverse=True
            ),
            categories=sorted({row.category for row in all_rows if row.category}),
            category=category,
        ),
    )
