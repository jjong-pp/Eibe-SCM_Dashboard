"""
매출 대시보드 API.

한 번의 호출로 화면 한 장을 채운다. 구 Sales Hub 는 시트를 통째로 받아
브라우저에서 계산했는데, 그러면 원장 전체가 클라이언트로 나가고 계산 규칙이
화면마다 갈린다.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_viewer
from app.database import get_db
from app.schemas.analytics import (
    AlertResponse,
    ChannelMixResponse,
    ComparisonResponse,
    DashboardMetaResponse,
    DashboardResponse,
    KpiResponse,
    MomentumResponse,
    PeriodResponse,
    PortfolioResponse,
    PortfolioRowResponse,
    PromotionEffectResponse,
    TotalsResponse,
    TrendResponse,
    TrendSeriesResponse,
)
from app.services import analytics

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/analytics",
    tags=["매출 분석"],
    dependencies=[Depends(require_viewer)],
)


def _period(period: analytics.Period) -> PeriodResponse:
    return PeriodResponse(start=period.start, end=period.end, days=period.days)


def _totals(totals: analytics.Totals) -> TotalsResponse:
    return TotalsResponse(qty=totals.qty, amount=totals.amount)


def _comparison(comparison: analytics.Comparison) -> ComparisonResponse:
    return ComparisonResponse(
        period=_period(comparison.period),
        previous_period=_period(comparison.previous_period),
        current=_totals(comparison.current),
        previous=_totals(comparison.previous),
        qty_pct=round(comparison.qty_pct, 2),
        amount_pct=round(comparison.amount_pct, 2),
    )


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    brand_id: int | None = None,
    anchor: str | None = Query(
        default=None,
        description="week:2026-W25 · month:2026-06 · 2026-06-19 · 생략 시 오늘",
    ),
    category: str | None = None,
    trend_unit: analytics.TrendUnit = analytics.TrendUnit.WEEK,
    trend_value: analytics.TrendValue = analytics.TrendValue.AMOUNT,
    trend_basis: analytics.TrendBasis = analytics.TrendBasis.CHANNEL_GROUP,
    trend_span: int = Query(analytics.TREND_DEFAULT_RANGE, ge=1, le=52),
    as_of: date | None = Query(
        default=None, description="'오늘'을 대신할 기준일 (테스트·과거 조회용)"
    ),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    """대시보드 한 장.

    해석할 수 없는 `anchor` 는 예외 대신 오늘 기준으로 떨어진다 — 조회
    화면이 잘못된 입력 하나로 통째로 깨지면 안 된다.
    """
    result = analytics.compute_dashboard(
        db,
        brand_id=brand_id,
        anchor=anchor,
        category=category,
        today=as_of,
        trend_unit=trend_unit,
        trend_value=trend_value,
        trend_basis=trend_basis,
        trend_span=trend_span,
    )

    kpi = result.kpi
    return DashboardResponse(
        brand_id=result.brand_id,
        kpi=KpiResponse(
            week=_comparison(kpi.week),
            month=_comparison(kpi.month),
            momentum=MomentumResponse(
                avg_qty=round(kpi.momentum.avg_qty, 1),
                avg_amount=kpi.momentum.avg_amount,
                qty_diff=round(kpi.momentum.qty_diff, 1),
                amount_diff=kpi.momentum.amount_diff,
                qty_pct=round(kpi.momentum.qty_pct, 2),
                amount_pct=round(kpi.momentum.amount_pct, 2),
            ),
            week_label=kpi.week_label,
            month_label=kpi.month_label,
        ),
        channel_mix=[
            ChannelMixResponse(
                channel_group=row.channel_group,
                qty=row.qty,
                amount=row.amount,
                share_pct=round(row.share_pct, 2),
                share_wow_pp=round(row.share_wow_pp, 2),
                share_mom_pp=round(row.share_mom_pp, 2),
                qty_wow_pct=round(row.qty_wow_pct, 2),
            )
            for row in result.channel_mix
        ],
        portfolio=PortfolioResponse(
            growth=[
                PortfolioRowResponse(
                    lineup=row.lineup,
                    qty=row.qty,
                    amount=row.amount,
                    qty_pct=None if row.qty_pct is None else round(row.qty_pct, 2),
                    is_new=row.is_new,
                )
                for row in result.portfolio.growth
            ],
            decline=[
                PortfolioRowResponse(
                    lineup=row.lineup,
                    qty=row.qty,
                    amount=row.amount,
                    qty_pct=None if row.qty_pct is None else round(row.qty_pct, 2),
                    is_new=row.is_new,
                )
                for row in result.portfolio.decline
            ],
        ),
        alerts=[
            AlertResponse(
                kind=alert.kind.value,
                scope=alert.scope.value,
                name=alert.name,
                change_pct=round(alert.change_pct, 2),
                related_events=list(alert.related_events),
            )
            for alert in result.alerts
        ],
        promotions=[
            PromotionEffectResponse(
                event_name=effect.event_name,
                channel_name=effect.channel_name,
                channel_group=effect.channel_group,
                lineup=effect.lineup,
                period=_period(effect.period),
                qty=effect.qty,
                amount=effect.amount,
                elapsed_days=effect.elapsed_days,
                baseline_daily_qty=round(effect.baseline_daily_qty, 2),
                event_daily_qty=round(effect.event_daily_qty, 2),
                lift_pct=(
                    None if effect.lift_pct is None else round(effect.lift_pct, 2)
                ),
                overlaps_week=effect.overlaps_week,
                is_upcoming=effect.is_upcoming,
                is_schedule_only=effect.is_schedule_only,
            )
            for effect in result.promotions
        ],
        trend=TrendResponse(
            labels=result.trend.labels,
            series=[
                TrendSeriesResponse(
                    label=series.label, total=series.total, data=series.data
                )
                for series in result.trend.series
            ],
            unit=result.trend.unit.value,
            value=result.trend.value.value,
            basis=result.trend.basis.value,
            truncated=result.trend.truncated,
        ),
        meta=DashboardMetaResponse(**vars(result.meta)),
    )
