"""
주차 계산 검증.

연말·연초 경계가 핵심이다. 2025-12-29(월)은 달력상 2025년이지만 ISO 기준
2026년 1주차에 속한다. 이 처리를 틀리면 12월 마지막 주 매출이 통째로
엉뚱한 해에 집계된다.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.dates import (
    IsoWeek,
    add_months,
    iso_week_of,
    month_key,
    recent_weeks,
    week_range,
)


class TestIsoWeekOf:
    @pytest.mark.parametrize(
        ("day", "expected"),
        [
            ("2025-12-28", (2025, 52)),  # 일요일 — 아직 2025년 52주차
            ("2025-12-29", (2026, 1)),   # 월요일 — ISO 기준 벌써 2026년
            ("2026-01-01", (2026, 1)),
            ("2026-01-04", (2026, 1)),   # 일요일 — 여전히 1주차
            ("2026-01-05", (2026, 2)),
            ("2026-12-31", (2026, 53)),  # 2026년은 53주차까지 있다
        ],
    )
    def test_year_boundary(self, day: str, expected: tuple[int, int]) -> None:
        assert tuple(iso_week_of(date.fromisoformat(day))) == expected


class TestIsoWeekBounds:
    def test_start_is_monday_end_is_sunday(self) -> None:
        week = IsoWeek(2026, 25)
        assert week.start_date().isoweekday() == 1
        assert week.end_date().isoweekday() == 7

    def test_span_is_seven_days(self) -> None:
        week = IsoWeek(2026, 25)
        assert (week.end_date() - week.start_date()).days == 6

    def test_every_day_in_span_maps_back_to_same_week(self) -> None:
        week = IsoWeek(2026, 25)
        cursor = week.start_date()
        while cursor <= week.end_date():
            assert iso_week_of(cursor) == week
            cursor += timedelta(days=1)

    def test_key_is_zero_padded(self) -> None:
        assert IsoWeek(2026, 3).key == "2026-W03"


class TestIsoWeekShift:
    def test_shift_crosses_year_boundary(self) -> None:
        # 2026년 1주차에서 한 주 뒤로 가면 2025년 52주차
        assert IsoWeek(2026, 1).shift(-1) == IsoWeek(2025, 52)

    def test_shift_forward_and_back_is_identity(self) -> None:
        week = IsoWeek(2026, 25)
        assert week.shift(13).shift(-13) == week

    def test_shift_across_53_week_year(self) -> None:
        # 2026년은 53주차가 존재하므로 건너뛰면 안 된다
        assert IsoWeek(2026, 53).shift(1) == IsoWeek(2027, 1)


class TestIsoWeekLabel:
    def test_label_uses_english_month_abbreviation(self) -> None:
        """주차 표기 규칙: 한글이 아닌 영문 3글자 월약어."""
        label = iso_week_of(date(2026, 6, 15)).label()
        assert label.startswith("Jun-W")

    def test_label_has_no_hangul(self) -> None:
        for month in range(1, 13):
            label = iso_week_of(date(2026, month, 15)).label()
            assert all(ord(ch) < 128 for ch in label), label


class TestWeekRange:
    def test_single_day_gives_one_week(self) -> None:
        day = date(2026, 6, 15)
        assert week_range(day, day) == [IsoWeek(2026, 25)]

    def test_reversed_range_is_empty(self) -> None:
        assert week_range(date(2026, 6, 15), date(2026, 6, 1)) == []

    def test_covers_every_week_without_duplicates(self) -> None:
        weeks = week_range(date(2026, 1, 1), date(2026, 3, 31))
        assert len(weeks) == len(set(weeks))
        assert weeks == sorted(weeks, key=lambda w: w.start_date())

    def test_includes_final_partial_week(self) -> None:
        # 종료일이 주 중간이어도 그 주가 포함되어야 한다
        weeks = week_range(date(2026, 6, 1), date(2026, 6, 17))
        assert iso_week_of(date(2026, 6, 17)) in weeks


class TestRecentWeeks:
    def test_returns_requested_count_oldest_first(self) -> None:
        weeks = recent_weeks(IsoWeek(2026, 25), 12)
        assert len(weeks) == 12
        assert weeks[-1] == IsoWeek(2026, 25)
        assert weeks == sorted(weeks, key=lambda w: w.start_date())

    def test_zero_or_negative_gives_empty(self) -> None:
        assert recent_weeks(IsoWeek(2026, 25), 0) == []
        assert recent_weeks(IsoWeek(2026, 25), -3) == []

    def test_crosses_year_boundary_correctly(self) -> None:
        weeks = recent_weeks(IsoWeek(2026, 2), 4)
        assert weeks[0] == IsoWeek(2025, 51)


class TestMonthHelpers:
    def test_month_key_is_zero_padded(self) -> None:
        assert month_key(date(2026, 6, 15)) == "2026-06"

    def test_add_months_basic(self) -> None:
        assert add_months(date(2026, 6, 15), 6) == date(2026, 12, 15)

    def test_add_months_crosses_year(self) -> None:
        assert add_months(date(2026, 8, 10), 6) == date(2027, 2, 10)

    def test_add_months_clamps_to_month_end(self) -> None:
        # 1/31 에서 한 달 뒤는 2/28 (2026년은 평년)
        assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)

    def test_add_months_handles_december_rollover(self) -> None:
        assert add_months(date(2026, 12, 31), 1) == date(2027, 1, 31)

    def test_add_months_negative(self) -> None:
        assert add_months(date(2026, 3, 15), -6) == date(2025, 9, 15)
