"""纪念日的日期推算。

两个必须处理的边界：
- **2 月 29 日**：平年没有这天，退到 2 月 28 日
- **每月 31 日**：小月没有 31 号，退到当月最后一天

不处理这两种情况的话，`date(2027, 2, 29)` 会直接抛 ValueError 把页面打挂。
"""

import calendar
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Anniversary

RECURRENCE_YEARLY = "yearly"
RECURRENCE_MONTHLY = "monthly"
RECURRENCE_ONCE = "once"

RECURRENCE_LABELS = {
    RECURRENCE_YEARLY: "每年",
    RECURRENCE_MONTHLY: "每月",
    RECURRENCE_ONCE: "仅一次",
}


def clamp_to_month(year: int, month: int, day: int) -> date:
    """把「年月日」夹到该月实际存在的日期。"""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def next_occurrence(anniversary: Anniversary, today: date) -> date | None:
    """下一次发生的日期。今天就是的话返回今天；一次性的且已过去则返回 None。"""
    start = anniversary.start_date

    if anniversary.recurrence == RECURRENCE_ONCE:
        return start if start >= today else None

    if anniversary.recurrence == RECURRENCE_MONTHLY:
        candidate = clamp_to_month(today.year, today.month, start.day)
        if candidate < today:
            candidate = clamp_to_month(*_next_month(today.year, today.month), start.day)
        return candidate

    # 默认按每年算
    candidate = clamp_to_month(today.year, start.month, start.day)
    if candidate < today:
        candidate = clamp_to_month(today.year + 1, start.month, start.day)
    return candidate


def days_until(anniversary: Anniversary, today: date) -> int | None:
    """距离下次还有几天。0 = 就是今天。"""
    upcoming = next_occurrence(anniversary, today)
    return None if upcoming is None else (upcoming - today).days


def days_together(anniversary: Anniversary, today: date) -> int:
    """从起始日算起的第几天。起始日当天记作第 1 天。

    起始日还没到（比如未来的预产期）时返回 0。
    """
    elapsed = (today - anniversary.start_date).days
    return elapsed + 1 if elapsed >= 0 else 0


def years_elapsed(anniversary: Anniversary, today: date) -> int:
    """已经过了几周年。用于「3 周年快乐」这种文案。"""
    if today < anniversary.start_date:
        return 0
    years = today.year - anniversary.start_date.year
    this_years = clamp_to_month(
        today.year, anniversary.start_date.month, anniversary.start_date.day
    )
    return years if today >= this_years else years - 1


@dataclass
class AnniversaryView:
    anniversary: Anniversary
    today: date

    @property
    def next_date(self) -> date | None:
        return next_occurrence(self.anniversary, self.today)

    @property
    def days_left(self) -> int | None:
        return days_until(self.anniversary, self.today)

    @property
    def is_today(self) -> bool:
        return self.days_left == 0

    @property
    def day_count(self) -> int:
        return days_together(self.anniversary, self.today)

    @property
    def years(self) -> int:
        return years_elapsed(self.anniversary, self.today)

    @property
    def recurrence_label(self) -> str:
        return RECURRENCE_LABELS.get(
            self.anniversary.recurrence, self.anniversary.recurrence
        )

    @property
    def countdown_text(self) -> str:
        left = self.days_left
        if left is None:
            return "已过去"
        if left == 0:
            return "就是今天 🎉"
        if left == 1:
            return "明天"
        return f"还有 {left} 天"

    @property
    def should_remind(self) -> bool:
        """是否进入提醒窗口。提醒逻辑会用到这个。"""
        left = self.days_left
        return left is not None and left <= self.anniversary.remind_days_before


def list_anniversaries(db: Session) -> list[Anniversary]:
    return list(db.scalars(select(Anniversary).order_by(Anniversary.start_date)))


def build_views(db: Session, today: date) -> list[AnniversaryView]:
    """按「下次发生的远近」排序，一次性且已过期的排最后。"""
    views = [AnniversaryView(a, today) for a in list_anniversaries(db)]
    return sorted(
        views,
        key=lambda v: (v.days_left is None, v.days_left if v.days_left is not None else 0),
    )
