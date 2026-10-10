"""统计页的数据序列。

缺失的日期用 null 填，让 Chart.js 把漏打卡的天画成断点——
补 0 会让图看起来像「那天偏差正好是 0」，是在骗人。
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ROLE_FEMALE, User
from app.services.kisses import balance_series, build_ledger
from app.services.records import list_records
from app.services.scoring import summarize

PERSON_HEX = {ROLE_FEMALE: "#f43f5e", "male": "#6366f1"}
DEFAULT_HEX = "#64748b"


def date_range(end: date, days: int) -> list[date]:
    start = end - timedelta(days=days - 1)
    return [start + timedelta(days=offset) for offset in range(days)]


def build_stats(db: Session, today: date, days: int = 90) -> dict:
    days = max(7, min(365, days))
    axis = date_range(today, days)
    labels = [day.isoformat() for day in axis]

    people = []
    for user in db.scalars(select(User).order_by(User.id)):
        records = list_records(db, user.id, axis[0], axis[-1])
        by_date = {record.record_date: record for record in records}

        deviations: list[int | None] = []
        cumulative: list[int | None] = []
        running = 0
        for day in axis:
            record = by_date.get(day)
            if record is None:
                deviations.append(None)
            else:
                deviations.append(record.deviation_minutes)
                running += record.deviation_minutes
            # 累计曲线不留断点——没打卡那天累计值保持不变，这是真实情况
            cumulative.append(running)

        summary = summarize(records)
        people.append(
            {
                "display_name": user.display_name,
                "role": user.role,
                "metric": user.metric_label,
                "color": PERSON_HEX.get(user.role, DEFAULT_HEX),
                "target_minutes": user.target_minutes,
                "deviation": deviations,
                "cumulative": cumulative,
                "summary": {
                    "total_days": summary.total_days,
                    "on_target_days": summary.on_target_days,
                    "on_target_rate": round(summary.on_target_rate, 4),
                    "cumulative_deviation": summary.cumulative_deviation,
                    "current_streak": summary.current_streak,
                    "best_streak": summary.best_streak,
                },
            }
        )

    ledger = build_ledger(db, today)

    return {
        "days": days,
        "labels": labels,
        "people": people,
        # 亲亲余额走势。单位是「百分之一个」，前端显示时除以 100
        "kiss_balance_centi": balance_series(db, axis),
        "kiss": {
            "balance_centi": ledger.balance_centi,
            "custom_balance_centi": ledger.custom_balance_centi,
            "custom_reward_name": ledger.config.custom_reward_name,
            "minutes_per_kiss": ledger.config.minutes_per_kiss,
            "debtor_name": ledger.debtor_name,
            "creditor_name": ledger.creditor_name,
            "owed_centi": ledger.owed_centi,
            "is_settled": ledger.is_settled,
        },
    }
