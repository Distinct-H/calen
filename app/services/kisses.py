"""亲亲兑换与每日结算。

规则：
- ``pair_diff = 女生偏差 - 男生偏差``（沿用 scoring.compute_pair_diff 的定向）
- **男生领先**（pair_diff < 0）→ 领先的分钟数换成亲亲，女生欠的**增加**
- **女生领先**（pair_diff > 0）→ 按配置的模式二选一：
  - ``deduct``：同样换成亲亲，但是**抵扣**女生欠的
  - ``custom``：亲亲不变，改成累积自定义奖励（名称和比率都可配）
- 两人都填了才结算；有一方没填就没法比较，不产生结算

存档原则和达标值一致：**今天是活的，历史是存档**。改兑换比率只会重算今天，
历史结算保留各自当时的比率——否则「欠了多少」会在改一次设置后全部变样。

亲亲以「百分之一个」为单位用整数存（``*_centi``），避开浮点误差，也避开
Decimal 在 SQLite 和 Postgres 上的方言差异。
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ROLE_FEMALE,
    DailyRecord,
    KissConfig,
    KissSettlement,
    User,
)

# 1 个亲亲 = 100 centi
KISS_SCALE = 100

MODE_DEDUCT = "deduct"
MODE_CUSTOM = "custom"

MODE_LABELS = {
    MODE_DEDUCT: "抵扣亲亲（女生领先时减少欠的）",
    MODE_CUSTOM: "换成别的奖励（亲亲不变）",
}

MIN_RATIO = 1
MAX_RATIO = 600  # 10 小时换 1 个，再大就没意义了


# ── 配置 ────────────────────────────────────────────────────────


def get_config(db: Session) -> KissConfig:
    """取全局单行配置，不存在就按默认值建一条。"""
    config = db.get(KissConfig, 1)
    if config is None:
        config = KissConfig(id=1)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def clamp_ratio(value: int) -> int:
    return max(MIN_RATIO, min(MAX_RATIO, int(value)))


# ── 纯计算 ──────────────────────────────────────────────────────


def minutes_to_centi(minutes: int, minutes_per_unit: int) -> int:
    """分钟换成「百分之一个」。比率非法时返回 0 而不是炸掉。"""
    if minutes_per_unit <= 0:
        return 0
    return round(minutes * KISS_SCALE / minutes_per_unit)


@dataclass(frozen=True)
class Conversion:
    """一天的兑换结果，单位都是百分之一个。"""

    kiss_delta_centi: int
    custom_delta_centi: int


def convert(
    pair_diff_minutes: int,
    minutes_per_kiss: int,
    female_lead_mode: str,
    minutes_per_custom_unit: int,
) -> Conversion:
    """把当日的达标程度差额换成亲亲 / 自定义奖励。"""
    if pair_diff_minutes < 0:
        # 男生领先 → 女生欠的增加
        return Conversion(
            kiss_delta_centi=minutes_to_centi(-pair_diff_minutes, minutes_per_kiss),
            custom_delta_centi=0,
        )

    if pair_diff_minutes > 0:
        if female_lead_mode == MODE_CUSTOM:
            # 亲亲不动，换成别的奖励
            return Conversion(
                kiss_delta_centi=0,
                custom_delta_centi=minutes_to_centi(
                    pair_diff_minutes, minutes_per_custom_unit
                ),
            )
        # 抵扣：女生欠的减少
        return Conversion(
            kiss_delta_centi=-minutes_to_centi(pair_diff_minutes, minutes_per_kiss),
            custom_delta_centi=0,
        )

    return Conversion(0, 0)


# ── 结算 ────────────────────────────────────────────────────────


def get_settlement(db: Session, day: date) -> KissSettlement | None:
    return db.scalar(
        select(KissSettlement).where(KissSettlement.settle_date == day)
    )


def _pair(db: Session) -> tuple[User | None, User | None]:
    users = list(db.scalars(select(User).order_by(User.id)))
    female = next((u for u in users if u.role == ROLE_FEMALE), None)
    male = next((u for u in users if u.role != ROLE_FEMALE), None)
    return female, male


def _record(db: Session, user_id: int, day: date) -> DailyRecord | None:
    return db.scalar(
        select(DailyRecord).where(
            DailyRecord.user_id == user_id, DailyRecord.record_date == day
        )
    )


def settle_day(db: Session, day: date, today: date) -> KissSettlement | None:
    """结算某一天。

    两人都填了才算；有一方没填（或把记录删了）就撤掉已有结算——
    数据不完整时留着一条旧结算比没有更糟。
    """
    female, male = _pair(db)
    if female is None or male is None:
        return None

    female_record = _record(db, female.id, day)
    male_record = _record(db, male.id, day)
    existing = get_settlement(db, day)

    if female_record is None or male_record is None:
        if existing is not None:
            db.delete(existing)
            db.commit()
        return None

    pair_diff = female_record.deviation_minutes - male_record.deviation_minutes

    # 比率快照规则：新结算和今天的结算用当前配置，历史结算保留原比率
    if existing is None or day == today:
        config = get_config(db)
        ratio = config.minutes_per_kiss
        mode = config.female_lead_mode
        custom_ratio = config.minutes_per_custom_unit
        custom_name = config.custom_reward_name
    else:
        ratio = existing.minutes_per_kiss
        mode = existing.female_lead_mode
        custom_ratio = existing.minutes_per_custom_unit
        custom_name = existing.custom_reward_name

    result = convert(pair_diff, ratio, mode, custom_ratio)

    if existing is None:
        existing = KissSettlement(settle_date=day)
        db.add(existing)

    existing.female_deviation_minutes = female_record.deviation_minutes
    existing.male_deviation_minutes = male_record.deviation_minutes
    existing.pair_diff_minutes = pair_diff
    existing.minutes_per_kiss = ratio
    existing.female_lead_mode = mode
    existing.minutes_per_custom_unit = custom_ratio
    existing.custom_reward_name = custom_name
    existing.kiss_delta_centi = result.kiss_delta_centi
    existing.custom_delta_centi = result.custom_delta_centi

    db.commit()
    db.refresh(existing)
    return existing


def apply_config_change(
    db: Session,
    today: date,
    minutes_per_kiss: int,
    female_lead_mode: str,
    custom_reward_name: str,
    minutes_per_custom_unit: int,
) -> KissConfig:
    """改兑换规则。只重算今天那条结算，历史一条不动。"""
    config = get_config(db)
    config.minutes_per_kiss = clamp_ratio(minutes_per_kiss)
    config.female_lead_mode = (
        female_lead_mode if female_lead_mode in MODE_LABELS else MODE_DEDUCT
    )
    config.custom_reward_name = custom_reward_name.strip() or "小红花"
    config.minutes_per_custom_unit = clamp_ratio(minutes_per_custom_unit)
    db.commit()

    settle_day(db, today, today)
    return config


def resettle_all(db: Session, today: date) -> int:
    """给所有「两人都填了」的日期补结算。部署这个功能后的一次性回填用。

    已有结算的日期会沿用它原本的比率，不会被当前配置改写。
    """
    days = set(db.scalars(select(DailyRecord.record_date).distinct()))
    settled = 0
    for day in sorted(days):
        if settle_day(db, day, today) is not None:
            settled += 1
    return settled


# ── 余额与展示 ──────────────────────────────────────────────────


def balance_centi(db: Session) -> int:
    """女生欠男生的亲亲余额。负数表示反过来是男生欠女生。"""
    return int(
        db.scalar(
            select(func.coalesce(func.sum(KissSettlement.kiss_delta_centi), 0))
        )
        or 0
    )


def custom_balance_centi(db: Session) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(KissSettlement.custom_delta_centi), 0))
        )
        or 0
    )


def recent_settlements(db: Session, limit: int = 14) -> list[KissSettlement]:
    return list(
        db.scalars(
            select(KissSettlement)
            .order_by(KissSettlement.settle_date.desc())
            .limit(limit)
        )
    )


def balance_series(db: Session, axis: list[date]) -> list[int]:
    """给定日期轴上的亲亲余额走势（含轴开始之前的历史累计）。"""
    if not axis:
        return []

    before = int(
        db.scalar(
            select(func.coalesce(func.sum(KissSettlement.kiss_delta_centi), 0)).where(
                KissSettlement.settle_date < axis[0]
            )
        )
        or 0
    )

    deltas = {
        s.settle_date: s.kiss_delta_centi
        for s in db.scalars(
            select(KissSettlement).where(
                KissSettlement.settle_date >= axis[0],
                KissSettlement.settle_date <= axis[-1],
            )
        )
    }

    series = []
    running = before
    for day in axis:
        running += deltas.get(day, 0)
        series.append(running)
    return series


@dataclass
class KissLedger:
    """亲亲账本的视图模型。"""

    config: KissConfig
    balance_centi: int
    custom_balance_centi: int
    today_settlement: KissSettlement | None
    female: User | None
    male: User | None

    @property
    def female_name(self) -> str:
        return self.female.display_name if self.female else "女生"

    @property
    def male_name(self) -> str:
        return self.male.display_name if self.male else "男生"

    @property
    def is_settled(self) -> bool:
        return self.balance_centi == 0

    @property
    def debtor_name(self) -> str:
        """谁欠谁。余额为正是女生欠男生。"""
        return self.female_name if self.balance_centi > 0 else self.male_name

    @property
    def creditor_name(self) -> str:
        return self.male_name if self.balance_centi > 0 else self.female_name

    @property
    def owed_centi(self) -> int:
        """欠的数量，始终为非负——方向由 debtor_name 表达。"""
        return abs(self.balance_centi)

    @property
    def today_pending(self) -> bool:
        """今天还没结算（有人没填）。"""
        return self.today_settlement is None


def build_ledger(db: Session, today: date) -> KissLedger:
    female, male = _pair(db)
    return KissLedger(
        config=get_config(db),
        balance_centi=balance_centi(db),
        custom_balance_centi=custom_balance_centi(db),
        today_settlement=get_settlement(db, today),
        female=female,
        male=male,
    )
