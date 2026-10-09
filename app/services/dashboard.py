"""首页「今日」面板的视图模型组装。

把取数和计算从路由里剥出来，路由只负责渲染，逻辑可以单独测。
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.auth import get_partner
from app.models import ROLE_FEMALE, DailyRecord, User
from app.services.clock import today_in
from app.services.records import get_record, list_records
from app.services.scoring import Summary, compute_pair_diff, split_minutes, summarize


@dataclass
class PersonView:
    user: User
    record: DailyRecord | None
    summary: Summary

    @property
    def deviation(self) -> int | None:
        return self.record.deviation_minutes if self.record else None

    @property
    def filled(self) -> bool:
        return self.record is not None

    @property
    def target_hm(self) -> tuple[int, int]:
        return split_minutes(self.user.target_minutes)

    @property
    def actual_hm(self) -> tuple[int, int]:
        return split_minutes(self.record.actual_minutes) if self.record else (0, 0)

    @property
    def is_female(self) -> bool:
        return self.user.role == ROLE_FEMALE


@dataclass
class DashboardView:
    """``day`` 是查看者时区下的「今天」，双方都按这一天取记录。"""

    day: date
    me: PersonView
    partner: PersonView | None

    @property
    def people(self) -> list[PersonView]:
        return [self.me] if self.partner is None else [self.me, self.partner]

    @property
    def female(self) -> PersonView | None:
        return next((p for p in self.people if p.is_female), None)

    @property
    def male(self) -> PersonView | None:
        return next((p for p in self.people if not p.is_female), None)

    @property
    def pair_diff(self) -> int | None:
        """两人今日达标程度之差，固定按「女生 - 男生」定向，与谁在登录无关。

        正数 = 女生今天更达标；负数 = 男生今天更达标；
        任一方未填或身份不成对则为 None。
        """
        if self.female is None or self.male is None:
            return None
        return compute_pair_diff(self.female.deviation, self.male.deviation)

    @property
    def more_on_target(self) -> User | None:
        """今天谁更达标。打平或数据不全时返回 None。"""
        diff = self.pair_diff
        if not diff:  # None 或 0
            return None
        winner = self.female if diff > 0 else self.male
        return winner.user if winner else None


def _build_person(db: Session, user: User, day: date) -> PersonView:
    return PersonView(
        user=user,
        record=get_record(db, user.id, day),
        # 两人量级下全量加载即可，不值得为分页增加复杂度
        summary=summarize(list_records(db, user.id)),
    )


def build_dashboard(db: Session, user: User, day: date | None = None) -> DashboardView:
    day = day or today_in(user.timezone)
    partner = get_partner(db, user)
    return DashboardView(
        day=day,
        me=_build_person(db, user, day),
        partner=_build_person(db, partner, day) if partner else None,
    )
