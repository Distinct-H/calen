"""偏差计算与累计统计。纯函数，不依赖数据库。"""

from dataclasses import dataclass
from datetime import date

import pytest

from app.services.scoring import (
    MAX_MINUTES,
    clamp_minutes,
    compute_deviation,
    compute_pair_diff,
    split_minutes,
    summarize,
    to_minutes,
)


@dataclass
class Point:
    """最小的测试桩：只要有这两个属性就能喂给 summarize。"""

    record_date: date
    deviation_minutes: int


class TestComputeDeviation:
    def test_under_target_is_negative(self):
        # 睡了 7 小时，目标 8 小时 → 还差 60 分
        assert compute_deviation(420, 480) == -60

    def test_over_target_is_positive(self):
        # 锻炼 90 分，目标 60 分 → 超出 30 分
        assert compute_deviation(90, 60) == 30

    def test_exactly_on_target_is_zero(self):
        assert compute_deviation(480, 480) == 0


class TestComputePairDiff:
    def test_positive_means_female_more_on_target(self):
        # 女生超出 30，男生还差 20 → 女生领先 50
        assert compute_pair_diff(30, -20) == 50

    def test_negative_means_male_more_on_target(self):
        assert compute_pair_diff(-20, 30) == -50

    def test_tie(self):
        assert compute_pair_diff(15, 15) == 0

    @pytest.mark.parametrize("female,male", [(None, 10), (10, None), (None, None)])
    def test_missing_side_returns_none_not_zero(self, female, male):
        """缺一方时必须是 None —— 用 0 冒充会被误读成「打平」。"""
        assert compute_pair_diff(female, male) is None


class TestMinutesHelpers:
    def test_clamp_rejects_negative(self):
        assert clamp_minutes(-30) == 0

    def test_clamp_caps_at_one_day(self):
        assert clamp_minutes(99999) == MAX_MINUTES

    def test_to_minutes_combines_inputs(self):
        assert to_minutes(7, 30) == 450

    def test_to_minutes_treats_blank_as_zero(self):
        assert to_minutes(None, 45) == 45
        assert to_minutes(8, None) == 480

    def test_split_roundtrip(self):
        assert split_minutes(450) == (7, 30)
        assert to_minutes(*split_minutes(450)) == 450


class TestSummarize:
    def test_empty_is_all_zeros(self):
        summary = summarize([])
        assert summary.total_days == 0
        assert summary.cumulative_deviation == 0
        assert summary.on_target_rate == 0.0

    def test_cumulative_sums_signed_deviations(self):
        points = [
            Point(date(2026, 3, 1), 30),
            Point(date(2026, 3, 2), -60),
            Point(date(2026, 3, 3), 15),
        ]
        assert summarize(points).cumulative_deviation == -15

    def test_on_target_counts_zero_as_met(self):
        points = [
            Point(date(2026, 3, 1), 0),
            Point(date(2026, 3, 2), -1),
        ]
        summary = summarize(points)
        assert summary.on_target_days == 1
        assert summary.on_target_rate == 0.5

    def test_streak_broken_by_missed_target(self):
        points = [
            Point(date(2026, 3, 1), 10),
            Point(date(2026, 3, 2), 10),
            Point(date(2026, 3, 3), -5),  # 中断
            Point(date(2026, 3, 4), 10),
        ]
        summary = summarize(points)
        assert summary.best_streak == 2
        assert summary.current_streak == 1

    def test_streak_broken_by_date_gap(self):
        """漏打卡也算中断——否则「连续达标」这个数字会骗人。"""
        points = [
            Point(date(2026, 3, 1), 10),
            Point(date(2026, 3, 2), 10),
            # 3 月 3 日没有记录
            Point(date(2026, 3, 4), 10),
        ]
        summary = summarize(points)
        assert summary.best_streak == 2
        assert summary.current_streak == 1

    def test_unordered_input_is_handled(self):
        points = [
            Point(date(2026, 3, 3), 10),
            Point(date(2026, 3, 1), 10),
            Point(date(2026, 3, 2), 10),
        ]
        assert summarize(points).current_streak == 3
