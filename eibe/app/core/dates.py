"""
주차 · 월 계산 유틸.

Sales Hub 의 analytics.js 는 ISO 주차를 직접 구현했다(윤년/연말 경계 처리를
손으로 짠 60여 줄). Python 은 date.isocalendar() 가 표준으로 제공하므로
그대로 대체한다.

주차 표기는 기존 규칙을 따른다: 영문 월약어 3글자 + 주차 (예: Jun-W3).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import NamedTuple

MONTH_ABBR = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


class IsoWeek(NamedTuple):
    """ISO 8601 주차. 연말·연초 경계에서 iso_year 가 달력 연도와 다를 수 있다."""

    year: int
    week: int

    @property
    def key(self) -> str:
        return f"{self.year}-W{self.week:02d}"

    def start_date(self) -> date:
        """해당 주의 월요일."""
        return date.fromisocalendar(self.year, self.week, 1)

    def end_date(self) -> date:
        """해당 주의 일요일."""
        return date.fromisocalendar(self.year, self.week, 7)

    def shift(self, weeks: int) -> IsoWeek:
        return iso_week_of(self.start_date() + timedelta(weeks=weeks))

    def label(self) -> str:
        """`Jun-W3` 형식. 그 주가 속한 달(월요일 기준)의 몇 번째 주인지 센다."""
        monday = self.start_date()
        first_of_month = monday.replace(day=1)
        # 그 달의 첫 월요일부터 몇 주가 지났는지
        offset = (monday - first_of_month).days // 7 + 1
        return f"{MONTH_ABBR[monday.month - 1]}-W{offset}"


def iso_week_of(value: date) -> IsoWeek:
    cal = value.isocalendar()
    return IsoWeek(cal.year, cal.week)


def week_range(start: date, end: date) -> list[IsoWeek]:
    """start~end 를 포함하는 ISO 주차 목록 (중복 없이, 시간순)."""
    if start > end:
        return []

    weeks: list[IsoWeek] = []
    seen: set[tuple[int, int]] = set()
    cursor = start
    while cursor <= end:
        wk = iso_week_of(cursor)
        if wk not in seen:
            seen.add(wk)
            weeks.append(wk)
        cursor += timedelta(days=7)

    # 마지막 주가 누락될 수 있어 한 번 더 확인한다.
    last = iso_week_of(end)
    if last not in seen:
        weeks.append(last)

    return weeks


def recent_weeks(anchor: IsoWeek, count: int) -> list[IsoWeek]:
    """anchor 를 포함한 직전 count 개 주차 (오래된 것부터)."""
    if count <= 0:
        return []
    return [anchor.shift(-offset) for offset in range(count - 1, -1, -1)]


def month_key(value: date) -> str:
    """`YYYY-MM`."""
    return f"{value.year}-{value.month:02d}"


def add_months(value: date, months: int) -> date:
    """월 단위 이동. 말일은 대상 월의 말일로 클램프한다 (1/31 +1개월 → 2/28)."""
    total = value.year * 12 + (value.month - 1) + months
    year, month = divmod(total, 12)
    month += 1

    # 다음 달 1일에서 하루 빼면 이번 달 말일
    if month == 12:
        last_day = 31
    else:
        last_day = (date(year, month + 1, 1) - timedelta(days=1)).day

    return date(year, month, min(value.day, last_day))
