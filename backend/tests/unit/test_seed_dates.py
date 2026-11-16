"""The week the demo plan lands in (#75).

Pure arithmetic, so it gets a unit test with an injected clock — which is the
only way to check a rule whose whole purpose is to still be true next month.
The bug these pin cost the project four weeks of a broken public demo: the
seeded plan was fixed to 2026-10-12, its week ended on the 18th, and nothing
failed until CI next ran.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from ration.seed.command import demo_start_date


class TestItLandsOnMonday:
    @pytest.mark.parametrize(
        ("today", "expected"),
        [
            (date(2026, 11, 16), date(2026, 11, 16)),  # a Monday is its own week start
            (date(2026, 11, 17), date(2026, 11, 16)),  # Tuesday
            (date(2026, 11, 22), date(2026, 11, 16)),  # Sunday, the last day of the week
            (date(2027, 1, 1), date(2026, 12, 28)),  # across a year boundary
            (date(2028, 2, 29), date(2028, 2, 28)),  # a leap day
        ],
    )
    def test_the_monday_of_that_week(self, today: date, expected: date) -> None:
        assert demo_start_date(today) == expected

    def test_every_day_of_a_year_lands_on_a_monday(self) -> None:
        """Monday because day_index 0 is Monday in the fixture.

        The day templates hang off the weekday — training on days 0 and 3, the
        long shift on day 2 — so a start that drifted off Monday would change
        what the demo demonstrates without changing a single number.
        """
        day = date(2026, 1, 1)
        for _ in range(366):
            assert demo_start_date(day).weekday() == 0
            day += timedelta(days=1)


class TestTheWeekAlwaysContainsToday:
    """The property that was silently false from 19 October 2026."""

    @pytest.mark.parametrize("offset", range(7))
    def test_today_is_inside_the_seven_days_it_starts(self, offset: int) -> None:
        today = date(2026, 11, 16) + timedelta(days=offset)
        start = demo_start_date(today)
        assert start <= today <= start + timedelta(days=6)

    def test_it_holds_on_every_day_of_a_year(self) -> None:
        day = date(2026, 1, 1)
        for _ in range(366):
            start = demo_start_date(day)
            assert start <= day <= start + timedelta(days=6), day
            day += timedelta(days=1)
