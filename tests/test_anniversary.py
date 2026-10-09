"""纪念日日期推算。闰年和月末是重点——处理不好会直接抛 ValueError。"""

from datetime import date

import pytest

from app.models import Anniversary
from app.services.anniversary import (
    AnniversaryView,
    clamp_to_month,
    days_together,
    days_until,
    next_occurrence,
    years_elapsed,
)


def make(start: date, recurrence: str = "yearly", remind: int = 3) -> Anniversary:
    return Anniversary(
        title="测试",
        start_date=start,
        recurrence=recurrence,
        show_countup=True,
        remind_days_before=remind,
    )


class TestClampToMonth:
    def test_leap_day_in_common_year_falls_back(self):
        assert clamp_to_month(2027, 2, 29) == date(2027, 2, 28)

    def test_leap_day_in_leap_year_is_kept(self):
        assert clamp_to_month(2028, 2, 29) == date(2028, 2, 29)

    def test_day_31_in_short_month(self):
        assert clamp_to_month(2026, 4, 31) == date(2026, 4, 30)
        assert clamp_to_month(2026, 2, 31) == date(2026, 2, 28)

    def test_normal_date_unchanged(self):
        assert clamp_to_month(2026, 10, 9) == date(2026, 10, 9)


class TestYearly:
    def test_upcoming_this_year(self):
        anniversary = make(date(2020, 12, 25))
        assert next_occurrence(anniversary, date(2026, 10, 9)) == date(2026, 12, 25)

    def test_already_passed_rolls_to_next_year(self):
        anniversary = make(date(2020, 3, 1))
        assert next_occurrence(anniversary, date(2026, 10, 9)) == date(2027, 3, 1)

    def test_today_counts_as_today(self):
        anniversary = make(date(2020, 10, 9))
        today = date(2026, 10, 9)
        assert next_occurrence(anniversary, today) == today
        assert days_until(anniversary, today) == 0

    def test_leap_day_anniversary_does_not_crash(self):
        """2/29 的纪念日在平年要退到 2/28，而不是抛异常。"""
        anniversary = make(date(2024, 2, 29))
        assert next_occurrence(anniversary, date(2027, 1, 1)) == date(2027, 2, 28)
        assert next_occurrence(anniversary, date(2028, 1, 1)) == date(2028, 2, 29)

    def test_days_until_crosses_year_boundary(self):
        anniversary = make(date(2020, 1, 1))
        assert days_until(anniversary, date(2026, 12, 31)) == 1


class TestMonthly:
    def test_upcoming_this_month(self):
        anniversary = make(date(2024, 1, 20), recurrence="monthly")
        assert next_occurrence(anniversary, date(2026, 10, 9)) == date(2026, 10, 20)

    def test_passed_rolls_to_next_month(self):
        anniversary = make(date(2024, 1, 5), recurrence="monthly")
        assert next_occurrence(anniversary, date(2026, 10, 9)) == date(2026, 11, 5)

    def test_december_rolls_to_january(self):
        anniversary = make(date(2024, 1, 5), recurrence="monthly")
        assert next_occurrence(anniversary, date(2026, 12, 9)) == date(2027, 1, 5)

    def test_day_31_clamps_in_short_months(self):
        anniversary = make(date(2024, 1, 31), recurrence="monthly")
        assert next_occurrence(anniversary, date(2026, 4, 1)) == date(2026, 4, 30)


class TestOnce:
    def test_future_one_off(self):
        anniversary = make(date(2027, 5, 1), recurrence="once")
        assert next_occurrence(anniversary, date(2026, 10, 9)) == date(2027, 5, 1)

    def test_past_one_off_has_no_next(self):
        anniversary = make(date(2020, 5, 1), recurrence="once")
        assert next_occurrence(anniversary, date(2026, 10, 9)) is None
        assert days_until(anniversary, date(2026, 10, 9)) is None


class TestCountUp:
    def test_start_day_is_day_one(self):
        anniversary = make(date(2026, 10, 9))
        assert days_together(anniversary, date(2026, 10, 9)) == 1

    def test_counts_elapsed_days(self):
        anniversary = make(date(2026, 10, 1))
        assert days_together(anniversary, date(2026, 10, 9)) == 9

    def test_future_start_is_zero(self):
        anniversary = make(date(2027, 1, 1))
        assert days_together(anniversary, date(2026, 10, 9)) == 0

    @pytest.mark.parametrize(
        "today,expected",
        [
            (date(2026, 3, 9), 5),  # 周年日还没到
            (date(2026, 3, 10), 6),  # 正好周年日
            (date(2026, 3, 11), 6),
        ],
    )
    def test_years_elapsed(self, today, expected):
        assert years_elapsed(make(date(2020, 3, 10)), today) == expected


class TestView:
    def test_countdown_wording(self):
        today = date(2026, 10, 9)
        assert AnniversaryView(make(date(2020, 10, 9)), today).countdown_text == "就是今天 🎉"
        assert AnniversaryView(make(date(2020, 10, 10)), today).countdown_text == "明天"
        assert AnniversaryView(make(date(2020, 10, 20)), today).countdown_text == "还有 11 天"

    def test_remind_window(self):
        today = date(2026, 10, 9)
        # 提前 3 天提醒：10/12 在窗口内，10/13 不在
        assert AnniversaryView(make(date(2020, 10, 12), remind=3), today).should_remind
        assert not AnniversaryView(make(date(2020, 10, 13), remind=3), today).should_remind

    def test_zero_remind_days_only_fires_on_the_day(self):
        today = date(2026, 10, 9)
        assert AnniversaryView(make(date(2020, 10, 9), remind=0), today).should_remind
        assert not AnniversaryView(make(date(2020, 10, 10), remind=0), today).should_remind
