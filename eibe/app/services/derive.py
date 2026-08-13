"""
파생 집계 — 판매 원장 → 주차별 실적.

동기화 job 이 아니라 **재계산**이다. 원장이 진실이고 WeeklyMetric 은 그것을
읽기 쉽게 정리한 사본이므로, 언제 몇 번을 돌려도 같은 결과가 나와야 한다.

지켜야 할 성질:
  멱등     같은 입력에 같은 결과. 두 번 돌려도 값이 배가 되지 않는다.
  부분성   특정 주차 구간만 다시 계산할 수 있다. 3년치를 매번 훑지 않는다.
  보존     엑셀로 직접 올린 값(source=IMPORTED)은 재계산이 건드리지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Select, and_, func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.core.dates import IsoWeek, iso_week_of
from app.models.enums import MetricSource
from app.models.master import Channel, ProductAlias
from app.models.metrics import WeeklyMetric
from app.models.sales import SalesOrder

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RebuildResult:
    weeks_covered: int
    rows_written: int
    rows_deleted: int
    rows_preserved: int

    def __str__(self) -> str:
        return (
            f"{self.weeks_covered}주 재계산 — "
            f"{self.rows_written}건 기록, {self.rows_deleted}건 삭제, "
            f"{self.rows_preserved}건 보존(IMPORTED)"
        )


def resolve_sales_mappings(db: Session, *, only_unmapped: bool = True) -> int:
    """판매 원장의 원본 문자열을 품목·채널에 연결한다.

    업로드 시점에 매핑이 없던 건도, 나중에 별칭을 추가하면 이 함수로 다시
    해석된다. 원본 문자열을 보존해둔 덕분에 재업로드가 필요 없다.

    Args:
        only_unmapped: True 면 아직 매핑되지 않은 행만 손댄다. False 면
            전체를 다시 해석한다 (별칭이 잘못 연결됐던 경우).

    Returns:
        갱신된 행 수.
    """
    alias_map = {
        alias.source_name: alias.product_id for alias in db.scalars(select(ProductAlias))
    }
    channel_map = {channel.name: channel.id for channel in db.scalars(select(Channel))}

    stmt: Select[tuple[SalesOrder]] = select(SalesOrder)
    if only_unmapped:
        stmt = stmt.where(
            or_(SalesOrder.product_id.is_(None), SalesOrder.channel_id.is_(None))
        )

    updated = 0
    for order in db.scalars(stmt):
        product_id = alias_map.get(order.source_product_name)
        channel_id = channel_map.get(order.source_channel_name)

        changed = False
        if product_id is not None and order.product_id != product_id:
            order.product_id = product_id
            changed = True
        if channel_id is not None and order.channel_id != channel_id:
            order.channel_id = channel_id
            changed = True

        if changed:
            updated += 1

    db.commit()
    logger.info("판매 매핑 해석: %d건 갱신", updated)
    return updated


def unmapped_sources(db: Session) -> dict[str, list[str]]:
    """아직 매핑되지 않은 원본 값 목록.

    조용히 집계에서 빠지는 대신 화면에 드러내기 위한 것이다. 미매핑 건은
    창고를 특정할 수 없어 주차 집계에 포함되지 못한다.
    """
    products = db.scalars(
        select(SalesOrder.source_product_name)
        .where(SalesOrder.product_id.is_(None))
        .distinct()
    ).all()
    channels = db.scalars(
        select(SalesOrder.source_channel_name)
        .where(SalesOrder.channel_id.is_(None))
        .distinct()
    ).all()
    return {"products": list(products), "channels": list(channels)}


def _weeks_touched(db: Session, since: date | None, until: date | None) -> list[IsoWeek]:
    """재계산 대상 주차. 판매 원장에 실제로 존재하는 주차만 돌려준다."""
    stmt = select(SalesOrder.iso_year, SalesOrder.iso_week).distinct()
    if since is not None:
        stmt = stmt.where(SalesOrder.ship_date >= since)
    if until is not None:
        stmt = stmt.where(SalesOrder.ship_date <= until)

    weeks = [IsoWeek(year, week) for year, week in db.execute(stmt).all()]
    return sorted(weeks, key=lambda w: (w.year, w.week))


def rebuild_weekly_metrics(
    db: Session,
    *,
    since: date | None = None,
    until: date | None = None,
) -> RebuildResult:
    """판매 원장에서 주차별 집계를 다시 만든다.

    매핑되지 않은 판매 건(품목 또는 창고 미상)은 제외한다. 어느 거점의 재고를
    소진시켰는지 알 수 없으면 재고 지표에 넣을 수 없기 때문이다. 누락된 건은
    `unmapped_sources()` 로 확인한다.

    Args:
        since / until: 재계산할 출고일 범위. 생략하면 전체.
    """
    weeks = _weeks_touched(db, since, until)
    if not weeks:
        logger.info("재계산할 주차가 없습니다.")
        return RebuildResult(0, 0, 0, 0)

    week_keys = [(w.year, w.week) for w in weeks]

    # 손으로 올린 값은 건드리지 않는다. 어떤 (주차,품목,창고)가 보호 대상인지
    # 미리 확보해 두고, 파생 행만 지운다.
    preserved = set(
        db.execute(
            select(
                WeeklyMetric.iso_year,
                WeeklyMetric.iso_week,
                WeeklyMetric.product_id,
                WeeklyMetric.warehouse_id,
            ).where(
                WeeklyMetric.source == MetricSource.IMPORTED,
                tuple_(WeeklyMetric.iso_year, WeeklyMetric.iso_week).in_(week_keys),
            )
        ).all()
    )

    # synchronize_session="fetch" 를 쓰는 이유: False 로 두면 삭제된 행이 세션의
    # 아이덴티티 맵에 남는다. SQLite 가 rowid 를 재사용하면 새로 만든 행과 식별자가
    # 겹쳐 stale 객체를 읽게 된다.
    deleted = db.query(WeeklyMetric).filter(
        WeeklyMetric.source == MetricSource.DERIVED,
        tuple_(WeeklyMetric.iso_year, WeeklyMetric.iso_week).in_(week_keys),
    ).delete(synchronize_session="fetch")
    db.flush()

    # 집계는 SQL 로 내려보낸다. 날짜를 Date 로, 주차를 물리 컬럼으로 둔 덕분에
    # 파이썬으로 원장을 훑을 필요가 없다.
    aggregate = db.execute(
        select(
            SalesOrder.iso_year,
            SalesOrder.iso_week,
            SalesOrder.product_id,
            Channel.warehouse_id,
            func.sum(SalesOrder.qty),
            func.sum(SalesOrder.amount),
        )
        .join(Channel, SalesOrder.channel_id == Channel.id)
        .where(
            SalesOrder.product_id.is_not(None),
            Channel.warehouse_id.is_not(None),
            tuple_(SalesOrder.iso_year, SalesOrder.iso_week).in_(week_keys),
        )
        .group_by(
            SalesOrder.iso_year,
            SalesOrder.iso_week,
            SalesOrder.product_id,
            Channel.warehouse_id,
        )
    ).all()

    written = 0
    skipped = 0
    for iso_year, iso_week, product_id, warehouse_id, qty, amount in aggregate:
        if (iso_year, iso_week, product_id, warehouse_id) in preserved:
            skipped += 1
            continue

        db.add(
            WeeklyMetric(
                iso_year=iso_year,
                iso_week=iso_week,
                product_id=product_id,
                warehouse_id=warehouse_id,
                sales_qty=int(qty or 0),
                sales_amount=Decimal(amount or 0),
                # 출고량은 재고 스냅샷에서 따로 채운다. 판매만으로는 감모와
                # 이관을 알 수 없으므로 여기서 추정하지 않는다.
                outflow_qty=int(qty or 0),
                source=MetricSource.DERIVED,
            )
        )
        written += 1

    db.commit()

    result = RebuildResult(
        weeks_covered=len(weeks),
        rows_written=written,
        rows_deleted=deleted,
        rows_preserved=skipped,
    )
    logger.info("주차 집계 재계산 완료: %s", result)
    return result


def rebuild_for_orders(db: Session, orders: list[SalesOrder]) -> RebuildResult:
    """방금 업로드한 주문이 속한 주차만 다시 계산한다.

    엑셀 업로드 직후에 쓴다. 전체 재계산을 피해 업로드 응답이 빨라진다.
    """
    if not orders:
        return RebuildResult(0, 0, 0, 0)

    ship_dates = [order.ship_date for order in orders]
    return rebuild_weekly_metrics(db, since=min(ship_dates), until=max(ship_dates))


def apply_inventory_flow(db: Session, week: IsoWeek) -> int:
    """재고 스냅샷에서 기초·기말·출고량을 채운다.

    판매량만으로는 감모와 이관을 알 수 없다. 실제 재고 변화와 대조해야
    `출고 - 판매 = 설명되지 않는 감소분`이 나오고, 그것이 감모 버퍼가 된다.

        단순출고량 = 기초재고 + 입고 - 기말재고

    Returns:
        갱신된 집계 행 수.
    """
    from app.models.scm import Inbound, InventorySnapshot  # 순환 참조 회피

    week_start = week.start_date()
    week_end = week.end_date()

    def _stock_on(reference: date) -> dict[tuple[int, int], tuple[int, date]]:
        """해당 시점 이전의 가장 최근 스냅샷 기준 (품목,창고)별 재고.

        수량과 함께 **어느 날짜의 스냅샷을 썼는지** 돌려준다. 기초와 기말이
        같은 스냅샷을 가리키면 그 주의 재고 변화를 알 수 없다는 뜻이므로,
        호출부가 그것을 구분할 수 있어야 한다.
        """
        latest = db.execute(
            select(
                InventorySnapshot.product_id,
                InventorySnapshot.warehouse_id,
                func.max(InventorySnapshot.snapshot_date),
            )
            .where(InventorySnapshot.snapshot_date <= reference)
            .group_by(InventorySnapshot.product_id, InventorySnapshot.warehouse_id)
        ).all()
        if not latest:
            return {}

        used_date = {(p, w): d for p, w, d in latest}
        rows = db.execute(
            select(
                InventorySnapshot.product_id,
                InventorySnapshot.warehouse_id,
                func.sum(InventorySnapshot.qty),
            )
            .where(
                tuple_(
                    InventorySnapshot.product_id,
                    InventorySnapshot.warehouse_id,
                    InventorySnapshot.snapshot_date,
                ).in_([(p, w, d) for p, w, d in latest])
            )
            .group_by(InventorySnapshot.product_id, InventorySnapshot.warehouse_id)
        ).all()
        return {(p, w): (int(q or 0), used_date[(p, w)]) for p, w, q in rows}

    beginning = _stock_on(week_start)
    # 기말은 그 주가 끝난 직후 시점으로 본다. 주 1회(월요일) 스냅샷을 뜨는
    # 운영에서는 다음 주 월요일 값이 이번 주의 마감 재고가 된다.
    ending = _stock_on(week_end + timedelta(days=1))

    inbound_rows = db.execute(
        select(
            Inbound.product_id,
            Inbound.arrival_warehouse_id,
            func.sum(Inbound.unit_qty),
        )
        .where(
            Inbound.arrival_warehouse_id.is_not(None),
            Inbound.eta.between(week_start, week_end),
        )
        .group_by(Inbound.product_id, Inbound.arrival_warehouse_id)
    ).all()
    inbound = {(p, w): int(q or 0) for p, w, q in inbound_rows}

    metrics = db.scalars(
        select(WeeklyMetric).where(
            WeeklyMetric.iso_year == week.year,
            WeeklyMetric.iso_week == week.week,
            WeeklyMetric.source == MetricSource.DERIVED,
        )
    ).all()

    updated = 0
    for metric in metrics:
        key = (metric.product_id, metric.warehouse_id)
        begin = beginning.get(key)
        end = ending.get(key)

        # 재고 변화를 알 수 없는 경우에는 손대지 않는다. 판매 기반으로 이미
        # 채워둔 outflow_qty 를 0으로 덮어쓰면 평탄화 상수가 0이 되고,
        # 감모 버퍼가 `0 - 판매량`이라 음수로 폭주한다.
        #   - 스냅샷 자체가 없음
        #   - 기초·기말이 같은 스냅샷을 가리킴 (그 주에 새 스냅샷이 없었음)
        if begin is None or end is None or begin[1] == end[1]:
            continue

        begin_qty, _ = begin
        end_qty, _ = end
        in_qty = inbound.get(key, 0)

        metric.beginning_qty = begin_qty
        metric.ending_qty = end_qty
        metric.inbound_qty = in_qty
        # 음수가 나오면 입고 기록 누락이므로 판매량으로 대체한다.
        outflow = begin_qty + in_qty - end_qty
        metric.outflow_qty = outflow if outflow >= 0 else metric.sales_qty
        updated += 1

    db.commit()
    return updated


def load_history(
    db: Session, product_id: int, anchor: IsoWeek, weeks: int = 12
) -> tuple[list[int], list[int]]:
    """예측 입력용 이력 — (출고량, 판매량) 을 주차 순서대로.

    창고를 합산한 전사 기준이다. 빠진 주차는 0으로 채우지 않고 건너뛴다 —
    데이터가 없는 주를 0 수요로 잡으면 소진율을 과소평가하게 된다.
    """
    start = anchor.shift(-(weeks - 1))
    boundaries = [(w.year, w.week) for w in _week_span(start, anchor)]

    rows = db.execute(
        select(
            WeeklyMetric.iso_year,
            WeeklyMetric.iso_week,
            func.sum(WeeklyMetric.outflow_qty),
            func.sum(WeeklyMetric.sales_qty),
        )
        .where(
            WeeklyMetric.product_id == product_id,
            tuple_(WeeklyMetric.iso_year, WeeklyMetric.iso_week).in_(boundaries),
        )
        .group_by(WeeklyMetric.iso_year, WeeklyMetric.iso_week)
        .order_by(WeeklyMetric.iso_year, WeeklyMetric.iso_week)
    ).all()

    outflow = [int(o or 0) for _, _, o, _ in rows]
    sales = [int(s or 0) for _, _, _, s in rows]
    return outflow, sales


def _week_span(start: IsoWeek, end: IsoWeek) -> list[IsoWeek]:
    weeks: list[IsoWeek] = []
    cursor = start
    guard = 0
    while (cursor.year, cursor.week) <= (end.year, end.week) and guard < 520:
        weeks.append(cursor)
        cursor = cursor.shift(1)
        guard += 1
    return weeks


def current_week(reference: date | None = None) -> IsoWeek:
    return iso_week_of(reference or date.today())
