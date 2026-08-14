"""
매출 분석 서비스 테스트.

구 analytics.js 는 테스트가 없었다. 여기서 고정하는 것은 두 종류다:
  - 옮겨온 계산 규칙 (임계값 · 점유율 · 리프트)
  - 옮기면서 **바꾼** 판단 (경과일수 대칭 비교, 시작 전 행사, HTML 미포함)

바꾼 쪽은 테스트가 없으면 다음 사람이 "원본과 다르다"며 되돌릴 수 있다.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.services import analytics as A
from tests.factories import (
    make_alias,
    make_brand,
    make_channel,
    make_product,
    make_promotion,
    make_sales_order,
    make_warehouse,
)

# 2026-06-15 는 월요일이다. 이 날짜를 기준으로 주 경계를 계산한다.
MONDAY = date(2026, 6, 15)


@pytest.fixture
def world(db: Session):
    """브랜드 · 창고 · 채널 · 품목 · 별칭이 갖춰진 최소 환경."""
    brand = make_brand(db)
    warehouse = make_warehouse(db)

    coupang = make_channel(db, name="쿠팡", channel_group="온라인", warehouse=warehouse)
    emart = make_channel(db, name="이마트", channel_group="오프라인", warehouse=warehouse)
    # 그룹이 없고 주요 채널도 아닌 채널 — '기타'로 모여야 한다.
    etc = make_channel(db, name="떠리몰", channel_group=None, is_major=False)

    h12 = make_product(db, brand, product_code="H12", name="H12 Pro")
    l10 = make_product(db, brand, product_code="L10", name="L10 Ultra")
    make_alias(db, h12, "드리미 H12 Pro", "H12 시리즈")
    make_alias(db, h12, "H12PRO 무선", "H12 시리즈")
    make_alias(db, l10, "드리미 L10", "L10 시리즈")

    return {
        "brand": brand,
        "coupang": coupang,
        "emart": emart,
        "etc": etc,
        "h12": h12,
        "l10": l10,
    }


def sell(
    db: Session,
    world: dict,
    day: date,
    qty: int,
    *,
    channel: str = "쿠팡",
    source: str = "드리미 H12 Pro",
    amount: str = "1000",
):
    channel_map = {
        "쿠팡": world["coupang"],
        "이마트": world["emart"],
        "떠리몰": world["etc"],
    }
    product_map = {
        "드리미 H12 Pro": world["h12"],
        "H12PRO 무선": world["h12"],
        "드리미 L10": world["l10"],
    }
    return make_sales_order(
        db,
        world["brand"],
        ship_date=day,
        qty=qty,
        amount=amount,
        product=product_map.get(source),
        channel=channel_map[channel],
        source_product_name=source,
        source_channel_name=channel,
    )


# ══════════════════════════════════════════════════════════════════════
# 조회 기준 해석
# ══════════════════════════════════════════════════════════════════════


def test_empty_anchor_uses_today():
    anchor = A.resolve_anchor("", today=MONDAY)
    assert anchor.reference == MONDAY
    assert anchor.full_period is False


def test_week_anchor_points_at_that_sunday_and_covers_full_period():
    anchor = A.resolve_anchor("week:2026-W25", today=MONDAY)
    assert anchor.reference == date(2026, 6, 21)  # 25주차 일요일
    assert anchor.full_period is True


def test_month_anchor_points_at_month_end():
    anchor = A.resolve_anchor("month:2026-06", today=MONDAY)
    assert anchor.reference == date(2026, 6, 30)
    assert anchor.full_period is True


def test_plain_date_anchor_is_partial():
    anchor = A.resolve_anchor("2026-06-17", today=MONDAY)
    assert anchor.reference == date(2026, 6, 17)
    assert anchor.full_period is False


@pytest.mark.parametrize(
    "raw", ["week:2026-W99", "month:2026-13", "2026-02-30", "쓰레기", "week:abc"]
)
def test_unparseable_anchor_falls_back_to_today(raw: str):
    """해석할 수 없으면 예외 대신 오늘로 돌아온다. 조회 화면이 깨지면 안 된다."""
    anchor = A.resolve_anchor(raw, today=MONDAY)
    assert anchor.reference == MONDAY
    assert anchor.raw == ""


# ══════════════════════════════════════════════════════════════════════
# 기간 — 여기서 구 버전과 갈린다
# ══════════════════════════════════════════════════════════════════════


def test_partial_week_compares_against_the_same_elapsed_days():
    """수요일에 열면 3일 대 3일을 본다.

    구 버전은 이번 주만 기준일에서 자르고 직전 주는 일요일까지 통째로 썼다.
    그러면 주 중반에는 WoW 가 늘 폭락으로 보인다.
    """
    wednesday = MONDAY + timedelta(days=2)
    periods = A.build_periods(A.resolve_anchor(today=wednesday))

    assert periods.week == A.Period(MONDAY, wednesday)
    assert periods.week.days == 3
    assert periods.prev_week.days == 3
    assert periods.prev_week == A.Period(MONDAY - timedelta(days=7), wednesday - timedelta(days=7))


def test_full_week_anchor_compares_seven_days_to_seven_days():
    periods = A.build_periods(A.resolve_anchor("week:2026-W25", today=MONDAY))
    assert periods.week.days == 7
    assert periods.prev_week.days == 7


def test_month_to_date_compares_against_same_day_last_month():
    periods = A.build_periods(A.resolve_anchor("2026-06-17", today=MONDAY))
    assert periods.month == A.Period(date(2026, 6, 1), date(2026, 6, 17))
    assert periods.prev_month == A.Period(date(2026, 5, 1), date(2026, 5, 17))


def test_month_end_day_clamps_when_previous_month_is_shorter():
    """3/31 의 직전 달 같은 날은 2/28 이다. 없는 날짜를 만들지 않는다."""
    periods = A.build_periods(A.resolve_anchor("2026-03-31", today=MONDAY))
    assert periods.prev_month.end == date(2026, 2, 28)


def test_full_month_anchor_uses_whole_months():
    periods = A.build_periods(A.resolve_anchor("month:2026-06", today=MONDAY))
    assert periods.month == A.Period(date(2026, 6, 1), date(2026, 6, 30))
    assert periods.prev_month == A.Period(date(2026, 5, 1), date(2026, 5, 31))


def test_momentum_uses_four_preceding_full_weeks():
    periods = A.build_periods(A.resolve_anchor("week:2026-W25", today=MONDAY))
    assert len(periods.momentum_weeks) == A.MOMENTUM_WEEKS
    assert all(period.days == 7 for period in periods.momentum_weeks)
    # 가장 최근 것이 직전 주다.
    assert periods.momentum_weeks[0].start == MONDAY - timedelta(days=7)


# ══════════════════════════════════════════════════════════════════════
# 증감률
# ══════════════════════════════════════════════════════════════════════


def test_pct_change_from_zero_is_hundred_when_there_is_a_value():
    assert A.pct_change(10, 0) == 100.0


def test_pct_change_from_zero_to_zero_is_zero():
    assert A.pct_change(0, 0) == 0.0


def test_pct_change_handles_decimal_amounts():
    assert A.pct_change(Decimal("150"), Decimal("100")) == pytest.approx(50.0)


# ══════════════════════════════════════════════════════════════════════
# 원장 읽기
# ══════════════════════════════════════════════════════════════════════


def test_rows_resolve_lineup_through_alias(db: Session, world: dict):
    sell(db, world, MONDAY, 5, source="드리미 H12 Pro")
    sell(db, world, MONDAY, 3, source="H12PRO 무선")

    rows = A.load_rows(db)
    assert {row.lineup for row in rows} == {"H12 시리즈"}
    # 원본 표기는 그대로 남는다 — 추적을 잃지 않는다.
    assert {row.product_name for row in rows} == {"드리미 H12 Pro", "H12PRO 무선"}


def test_unmapped_source_keeps_its_own_name_as_lineup(db: Session, world: dict):
    """별칭이 없어도 화면이 비지 않는다. 원본 문자열이 그대로 라인업이 된다."""
    make_sales_order(
        db,
        world["brand"],
        ship_date=MONDAY,
        qty=7,
        product=None,
        channel=world["coupang"],
        source_product_name="정체불명 신제품",
    )
    rows = A.load_rows(db)
    assert rows[0].lineup == "정체불명 신제품"


def test_channel_without_group_falls_into_etc(db: Session, world: dict):
    """접두어로 그룹을 추측하지 않는다. 추측한 집계는 틀려도 드러나지 않는다."""
    sell(db, world, MONDAY, 5, channel="떠리몰")
    rows = A.load_rows(db)
    assert rows[0].channel_group == A.UNASSIGNED_GROUP


def test_rows_are_filtered_by_brand(db: Session, world: dict):
    other = make_brand(db, name="다른브랜드", slug="other")
    sell(db, world, MONDAY, 5)
    make_sales_order(db, other, ship_date=MONDAY, qty=99, channel=world["coupang"])

    assert len(A.load_rows(db, brand_id=world["brand"].id)) == 1
    assert len(A.load_rows(db)) == 2


# ══════════════════════════════════════════════════════════════════════
# KPI
# ══════════════════════════════════════════════════════════════════════


def test_kpi_compares_week_against_previous_week(db: Session, world: dict):
    sell(db, world, MONDAY, 30, amount="3000")
    sell(db, world, MONDAY - timedelta(days=7), 20, amount="2000")

    dashboard = A.compute_dashboard(db, anchor="week:2026-W25")
    week = dashboard.kpi.week
    assert week.current.qty == 30
    assert week.previous.qty == 20
    assert week.qty_pct == pytest.approx(50.0)
    assert week.amount_pct == pytest.approx(50.0)


def test_week_label_uses_english_month_abbreviation(db: Session, world: dict):
    """주차 표기는 `Jun-W3` 형식이다. 한글 주차 표기는 쓰지 않는다."""
    dashboard = A.compute_dashboard(db, anchor="week:2026-W25")
    assert dashboard.kpi.week_label == "Jun-W3"


def test_momentum_measures_gap_from_four_week_average(db: Session, world: dict):
    for offset in range(1, 5):
        sell(db, world, MONDAY - timedelta(days=7 * offset), 10)
    sell(db, world, MONDAY, 20)

    kpi = A.compute_dashboard(db, anchor="week:2026-W25").kpi
    assert kpi.momentum.avg_qty == pytest.approx(10.0)
    assert kpi.momentum.qty_diff == pytest.approx(10.0)
    assert kpi.momentum.qty_pct == pytest.approx(100.0)


# ══════════════════════════════════════════════════════════════════════
# 채널 믹스
# ══════════════════════════════════════════════════════════════════════


def test_channel_mix_shares_sum_to_one_hundred(db: Session, world: dict):
    sell(db, world, MONDAY, 10, channel="쿠팡", amount="7500")
    sell(db, world, MONDAY, 10, channel="이마트", amount="2500")

    mix = A.compute_dashboard(db, anchor="week:2026-W25").channel_mix
    shares = {row.channel_group: row.share_pct for row in mix}
    assert shares["온라인"] == pytest.approx(75.0)
    assert shares["오프라인"] == pytest.approx(25.0)
    assert sum(shares.values()) == pytest.approx(100.0)


def test_share_change_is_percentage_points_not_percent(db: Session, world: dict):
    """매출이 늘어도 남이 더 늘면 점유율은 떨어진다 — 증감률과 다른 값이다."""
    last_week = MONDAY - timedelta(days=7)
    sell(db, world, last_week, 10, channel="쿠팡", amount="5000")
    sell(db, world, last_week, 10, channel="이마트", amount="5000")
    sell(db, world, MONDAY, 10, channel="쿠팡", amount="6000")
    sell(db, world, MONDAY, 10, channel="이마트", amount="14000")

    mix = {
        row.channel_group: row
        for row in A.compute_dashboard(db, anchor="week:2026-W25").channel_mix
    }
    online = mix["온라인"]
    # 매출은 5,000 → 6,000 으로 늘었지만 점유율은 50% → 30% 로 떨어졌다.
    assert online.amount == Decimal("6000.00")
    assert online.share_pct == pytest.approx(30.0)
    assert online.share_wow_pp == pytest.approx(-20.0)


def test_major_channel_stays_listed_with_no_sales(db: Session, world: dict):
    """실적이 0인 주에도 주요 채널은 남는다. 사라진 채널과 안 팔린 채널은 다르다."""
    sell(db, world, MONDAY, 10, channel="쿠팡")

    mix = A.compute_dashboard(db, anchor="week:2026-W25").channel_mix
    groups = {row.channel_group for row in mix}
    assert "오프라인" in groups
    assert next(row for row in mix if row.channel_group == "오프라인").qty == 0


def test_mix_is_sorted_by_amount_descending(db: Session, world: dict):
    sell(db, world, MONDAY, 1, channel="쿠팡", amount="100")
    sell(db, world, MONDAY, 1, channel="이마트", amount="900")

    mix = A.compute_dashboard(db, anchor="week:2026-W25").channel_mix
    assert [row.channel_group for row in mix][:2] == ["오프라인", "온라인"]


# ══════════════════════════════════════════════════════════════════════
# 포트폴리오
# ══════════════════════════════════════════════════════════════════════


def test_new_lineup_has_no_percentage_and_leads_growth(db: Session, world: dict):
    """직전 달 실적이 없으면 증감률을 낼 수 없다. 큰 수로 채우지 않는다."""
    sell(db, world, date(2026, 6, 10), 50, source="드리미 L10")

    portfolio = A.compute_dashboard(db, anchor="month:2026-06").portfolio
    top = portfolio.growth[0]
    assert top.lineup == "L10 시리즈"
    assert top.is_new is True
    assert top.qty_pct is None


def test_disappeared_lineup_shows_as_minus_hundred(db: Session, world: dict):
    """목록에서 조용히 빠지면 문제 없음처럼 보인다."""
    sell(db, world, date(2026, 5, 10), 40, source="드리미 L10")
    sell(db, world, date(2026, 6, 10), 40, source="드리미 H12 Pro")

    portfolio = A.compute_dashboard(db, anchor="month:2026-06").portfolio
    gone = next(row for row in portfolio.decline if row.lineup == "L10 시리즈")
    assert gone.qty == 0
    assert gone.qty_pct == pytest.approx(-100.0)


def test_portfolio_ignores_lineups_below_minimum_qty(db: Session, world: dict):
    sell(db, world, date(2026, 6, 10), 3, source="드리미 L10")
    sell(db, world, date(2026, 6, 10), 50, source="드리미 H12 Pro")

    rows = A.load_rows(db)
    periods = A.build_periods(A.resolve_anchor("month:2026-06"))

    assert [r.lineup for r in A.compute_portfolio(rows, periods, min_qty=1).growth] == [
        "H12 시리즈",
        "L10 시리즈",
    ]
    # 3개짜리는 임계값에 걸려 빠진다.
    assert [r.lineup for r in A.compute_portfolio(rows, periods, min_qty=5).growth] == [
        "H12 시리즈"
    ]


# ══════════════════════════════════════════════════════════════════════
# 알림
# ══════════════════════════════════════════════════════════════════════


def test_product_alert_fires_at_the_documented_threshold(db: Session, world: dict):
    sell(db, world, MONDAY - timedelta(days=7), 10)
    sell(db, world, MONDAY, 15)  # +50% — 경계값

    alerts = A.compute_dashboard(db, anchor="week:2026-W25").alerts
    product = [a for a in alerts if a.scope is A.AlertScope.PRODUCT]
    assert len(product) == 1
    assert product[0].kind is A.AlertKind.UP
    assert product[0].change_pct == pytest.approx(A.ALERT_PRODUCT_UP_PCT)


def test_product_drop_alert_uses_its_own_threshold(db: Session, world: dict):
    sell(db, world, MONDAY - timedelta(days=7), 100)
    sell(db, world, MONDAY, 75)  # -25%

    alerts = A.compute_dashboard(db, anchor="week:2026-W25").alerts
    product = [a for a in alerts if a.scope is A.AlertScope.PRODUCT]
    assert product[0].kind is A.AlertKind.DOWN


def test_moderate_change_raises_no_alert(db: Session, world: dict):
    sell(db, world, MONDAY - timedelta(days=7), 100)
    sell(db, world, MONDAY, 110)  # +10%

    alerts = A.compute_dashboard(db, anchor="week:2026-W25").alerts
    assert [a for a in alerts if a.scope is A.AlertScope.PRODUCT] == []


def test_no_alert_when_previous_week_had_nothing(db: Session, world: dict):
    """0에서 늘어난 것은 늘 100% 라 임계값이 의미를 잃는다."""
    sell(db, world, MONDAY, 500)

    alerts = A.compute_dashboard(db, anchor="week:2026-W25").alerts
    assert [a for a in alerts if a.scope is A.AlertScope.PRODUCT] == []


def test_channel_rise_needs_a_bigger_jump_without_an_event(db: Session, world: dict):
    """행사가 없으면 30% 로는 알리지 않는다 — 50% 부터다."""
    sell(db, world, MONDAY - timedelta(days=7), 100, channel="쿠팡")
    sell(db, world, MONDAY, 135, channel="쿠팡")  # +35%

    alerts = A.compute_dashboard(db, anchor="week:2026-W25").alerts
    assert [a for a in alerts if a.scope is A.AlertScope.CHANNEL] == []


def test_channel_rise_with_an_overlapping_event_alerts_earlier(db: Session, world: dict):
    sell(db, world, MONDAY - timedelta(days=7), 100, channel="쿠팡")
    sell(db, world, MONDAY, 135, channel="쿠팡")
    make_promotion(
        db,
        world["brand"],
        start_date=MONDAY,
        end_date=MONDAY + timedelta(days=6),
        source_channel_name="쿠팡",
        source_product_name=None,
        event_name="쿠팡 특가",
    )

    alerts = A.compute_dashboard(db, anchor="week:2026-W25").alerts
    channel = [a for a in alerts if a.scope is A.AlertScope.CHANNEL]
    assert len(channel) == 1
    assert channel[0].related_events == ("쿠팡 특가",)


def test_alerts_are_capped_and_sorted_by_magnitude(db: Session, world: dict):
    """다섯 개를 넘기면 아무도 읽지 않는다."""
    last_week = MONDAY - timedelta(days=7)
    for index in range(8):
        source = f"제품{index}"
        make_sales_order(
            db, world["brand"], ship_date=last_week, qty=100,
            channel=world["coupang"], source_product_name=source,
        )
        make_sales_order(
            db, world["brand"], ship_date=MONDAY, qty=100 + index * 100,
            channel=world["coupang"], source_product_name=source,
        )

    alerts = A.compute_dashboard(db, anchor="week:2026-W25").alerts
    assert len(alerts) == A.ALERT_MAX
    magnitudes = [abs(alert.change_pct) for alert in alerts]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_alert_carries_no_markup(db: Session, world: dict):
    """구 버전은 알림 문구에 <strong> 을 박아 보냈다. 표현은 화면이 정한다."""
    sell(db, world, MONDAY - timedelta(days=7), 10)
    sell(db, world, MONDAY, 30)

    alert = A.compute_dashboard(db, anchor="week:2026-W25").alerts[0]
    assert "<" not in alert.name
    assert not hasattr(alert, "text")


# ══════════════════════════════════════════════════════════════════════
# 행사 효과
# ══════════════════════════════════════════════════════════════════════


def test_lift_compares_daily_rates_not_totals(db: Session, world: dict):
    """행사 기간과 기준선 길이가 다르므로 총량으로 비교하면 안 된다."""
    # 기준선 14일 동안 하루 1개 (총 14개)
    for offset in range(1, 15):
        sell(db, world, MONDAY - timedelta(days=offset), 1)
    # 행사 7일 동안 하루 2개 (총 14개 — 총량은 같다)
    for offset in range(7):
        sell(db, world, MONDAY + timedelta(days=offset), 2)

    make_promotion(
        db, world["brand"],
        start_date=MONDAY, end_date=MONDAY + timedelta(days=6),
    )

    effects = A.compute_dashboard(
        db, anchor="week:2026-W25", today=MONDAY + timedelta(days=6)
    ).promotions
    effect = effects[0]
    assert effect.baseline_daily_qty == pytest.approx(1.0)
    assert effect.event_daily_qty == pytest.approx(2.0)
    assert effect.lift_pct == pytest.approx(100.0)


def test_upcoming_event_reports_no_lift(db: Session, world: dict):
    """구 버전은 시작 전 행사를 -100% 로 내보내 실패한 것처럼 보였다."""
    for offset in range(1, 15):
        sell(db, world, MONDAY - timedelta(days=offset), 1)

    future = MONDAY + timedelta(days=30)
    make_promotion(
        db, world["brand"], start_date=future, end_date=future + timedelta(days=3)
    )

    effect = A.compute_dashboard(db, anchor="week:2026-W25").promotions[0]
    assert effect.is_upcoming is True
    assert effect.is_schedule_only is False
    assert effect.lift_pct is None
    assert effect.elapsed_days == 0


def test_started_event_with_no_sales_is_schedule_only(db: Session, world: dict):
    for offset in range(1, 15):
        sell(db, world, MONDAY - timedelta(days=offset), 1)

    make_promotion(
        db, world["brand"],
        start_date=MONDAY, end_date=MONDAY + timedelta(days=6),
    )

    effect = A.compute_dashboard(
        db, anchor="week:2026-W25", today=MONDAY + timedelta(days=6)
    ).promotions[0]
    assert effect.is_schedule_only is True
    assert effect.qty == 0
    assert effect.lift_pct == pytest.approx(-100.0)


def test_event_sales_do_not_run_ahead_of_the_reference_date(db: Session, world: dict):
    """과거 주차를 조회하면 그 시점까지만 집계한다."""
    make_promotion(
        db, world["brand"],
        start_date=MONDAY, end_date=MONDAY + timedelta(days=6),
    )
    sell(db, world, MONDAY, 5)
    sell(db, world, MONDAY + timedelta(days=5), 100)  # 기준일 이후

    effect = A.compute_dashboard(db, anchor="2026-06-16").promotions[0]
    assert effect.qty == 5
    assert effect.elapsed_days == 2


def test_lift_is_none_without_a_baseline(db: Session, world: dict):
    """직전 14일 판매가 0이면 배수를 낼 기준선이 없다. 99999 를 쓰지 않는다."""
    for offset in range(7):
        sell(db, world, MONDAY + timedelta(days=offset), 5)
    make_promotion(
        db, world["brand"],
        start_date=MONDAY, end_date=MONDAY + timedelta(days=6),
    )

    effect = A.compute_dashboard(
        db, anchor="week:2026-W25", today=MONDAY + timedelta(days=6)
    ).promotions[0]
    assert effect.baseline_daily_qty == 0
    assert effect.lift_pct is None


def test_event_without_channel_or_name_is_skipped(db: Session, world: dict):
    """어떤 판매에 붙일지 정할 수 없는 행사는 집계하지 않는다."""
    make_promotion(
        db, world["brand"], start_date=MONDAY, end_date=MONDAY,
        source_channel_name="쿠팡", event_name="",
    )
    assert A.compute_dashboard(db, anchor="week:2026-W25").promotions == []


# ══════════════════════════════════════════════════════════════════════
# 추이
# ══════════════════════════════════════════════════════════════════════


def test_trend_covers_the_requested_number_of_weeks(db: Session, world: dict):
    sell(db, world, MONDAY, 10, amount="1000")

    trend = A.compute_dashboard(db, anchor="week:2026-W25", trend_span=4).trend
    assert len(trend.labels) == 4
    assert trend.labels[-1] == "Jun-W3"
    series = next(s for s in trend.series if s.label == "온라인")
    assert series.data[-1] == Decimal("1000.00")
    assert series.data[0] == Decimal("0")


def test_trend_does_not_extend_past_the_reference_week(db: Session, world: dict):
    """오지 않은 주가 0으로 그려지면 그래프가 절벽처럼 보인다."""
    sell(db, world, MONDAY, 10, amount="1000")
    sell(db, world, MONDAY + timedelta(days=14), 999, amount="999999")

    trend = A.compute_dashboard(db, anchor="week:2026-W25", trend_span=4).trend

    assert trend.labels[-1] == "Jun-W3"
    series = next(s for s in trend.series if s.label == "온라인")
    # 기준주 이후의 999,999 원은 어느 칸에도 들어가지 않는다.
    assert series.total == Decimal("1000.00")
    assert sum(series.data) == Decimal("1000.00")


def test_trend_by_quantity_counts_units(db: Session, world: dict):
    sell(db, world, MONDAY, 7, amount="99999")

    trend = A.compute_dashboard(
        db, anchor="week:2026-W25", trend_value=A.TrendValue.QTY, trend_span=4
    ).trend
    series = next(s for s in trend.series if s.label == "온라인")
    assert series.data[-1] == Decimal(7)


def test_trend_basis_switches_the_grouping(db: Session, world: dict):
    sell(db, world, MONDAY, 5, source="드리미 H12 Pro")
    sell(db, world, MONDAY, 5, source="드리미 L10")

    trend = A.compute_dashboard(
        db, anchor="week:2026-W25", trend_basis=A.TrendBasis.LINEUP, trend_span=4
    ).trend
    assert {s.label for s in trend.series} == {"H12 시리즈", "L10 시리즈"}


def test_monthly_trend_uses_month_labels(db: Session, world: dict):
    sell(db, world, MONDAY, 5)

    trend = A.compute_dashboard(
        db, anchor="month:2026-06", trend_unit=A.TrendUnit.MONTH, trend_span=4
    ).trend
    assert trend.labels[-1] == "2026.6"
    assert trend.labels[0] == "2026.3"


def test_unsupported_trend_span_falls_back_to_default(db: Session, world: dict):
    trend = A.compute_dashboard(db, anchor="week:2026-W25", trend_span=7).trend
    assert len(trend.labels) == A.TREND_DEFAULT_RANGE


# ══════════════════════════════════════════════════════════════════════
# 대시보드 전체
# ══════════════════════════════════════════════════════════════════════


def test_category_filter_still_offers_the_other_categories(db: Session, world: dict):
    """한 번 고르면 다른 카테고리로 옮겨갈 수 없게 되면 안 된다."""
    order = sell(db, world, MONDAY, 5)
    order.category = "가전"
    other = sell(db, world, MONDAY, 5, source="드리미 L10")
    other.category = "생활용품"
    db.commit()

    dashboard = A.compute_dashboard(db, anchor="week:2026-W25", category="가전")
    assert dashboard.meta.row_count == 1
    assert dashboard.meta.categories == ["가전", "생활용품"]


def test_meta_lists_available_periods_newest_first(db: Session, world: dict):
    sell(db, world, date(2026, 5, 4), 1)
    sell(db, world, date(2026, 6, 15), 1)

    meta = A.compute_dashboard(db, anchor="week:2026-W25").meta
    assert meta.week_keys == ["2026-W25", "2026-W19"]
    assert meta.month_keys == ["2026-06", "2026-05"]


def test_dashboard_on_empty_ledger_does_not_crash(db: Session):
    """데이터가 없어도 화면이 떠야 한다."""
    dashboard = A.compute_dashboard(db)
    assert dashboard.kpi.week.current.qty == 0
    assert dashboard.kpi.week.qty_pct == 0.0
    assert dashboard.channel_mix == []
    assert dashboard.alerts == []
    assert dashboard.meta.row_count == 0
