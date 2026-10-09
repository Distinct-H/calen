"""偏差值计算。

★ 全应用唯一的计算逻辑所在地。以后想换公式（改成积分制、加权重、
加惩罚项等），只改这个文件，其余代码不用动。
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence

MINUTES_PER_DAY = 24 * 60

# 输入合法区间。睡眠/锻炼时长不可能超过一天，也不会是负数。
MIN_MINUTES = 0
MAX_MINUTES = MINUTES_PER_DAY


class HasDeviation(Protocol):
    """只要有这两个属性就能参与统计——ORM 对象和测试桩都适用。"""

    record_date: date
    deviation_minutes: int


def compute_deviation(actual_minutes: int, target_minutes: int) -> int:
    """实际 - 达标。

    负数 = 距离达标还差多少分钟；正数 = 超出达标多少分钟；0 = 刚好达标。
    """
    return actual_minutes - target_minutes


def compute_pair_diff(
    female_deviation: int | None, male_deviation: int | None
) -> int | None:
    """两人达标程度之差。

    正数 = 女生今天更达标，负数 = 男生今天更达标。
    任一方当天没填就返回 None（没法比较，不要拿 0 冒充）。
    """
    if female_deviation is None or male_deviation is None:
        return None
    return female_deviation - male_deviation


def clamp_minutes(minutes: int) -> int:
    """把输入夹到合法区间，防止手滑输入 99999 把图表拉崩。"""
    return max(MIN_MINUTES, min(MAX_MINUTES, minutes))


def to_minutes(hours: int | None, minutes: int | None) -> int:
    """「小时 + 分钟」两个输入框合成总分钟数。手机上比输入纯分钟好填。"""
    return clamp_minutes((hours or 0) * 60 + (minutes or 0))


def split_minutes(total: int) -> tuple[int, int]:
    """总分钟数拆回 (小时, 分钟)，用于回填表单。"""
    total = abs(int(total))
    return divmod(total, 60)


@dataclass(frozen=True)
class Summary:
    """一段时间内的累计口径。"""

    total_days: int
    on_target_days: int
    cumulative_deviation: int
    current_streak: int
    best_streak: int

    @property
    def on_target_rate(self) -> float:
        """达标率，0.0 ~ 1.0。无记录时返回 0。"""
        if self.total_days == 0:
            return 0.0
        return self.on_target_days / self.total_days


def summarize(records: Sequence[HasDeviation]) -> Summary:
    """汇总累计偏差、达标天数和连续达标。

    连续达标的中断条件有两个：当天没达标，或者日期不连续（漏打卡算中断）。
    ``current_streak`` 是截至「最后一条记录」的连续天数，不感知今天是哪天。
    """
    if not records:
        return Summary(0, 0, 0, 0, 0)

    ordered = sorted(records, key=lambda r: r.record_date)

    cumulative = 0
    on_target_days = 0
    run = 0
    best = 0
    previous: date | None = None

    for record in ordered:
        cumulative += record.deviation_minutes

        if record.deviation_minutes >= 0:
            on_target_days += 1
            contiguous = previous is not None and (record.record_date - previous).days == 1
            run = run + 1 if contiguous else 1
        else:
            run = 0

        best = max(best, run)
        previous = record.record_date

    return Summary(
        total_days=len(ordered),
        on_target_days=on_target_days,
        cumulative_deviation=cumulative,
        current_streak=run,
        best_streak=best,
    )
