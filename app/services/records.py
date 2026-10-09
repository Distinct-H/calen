"""每日打卡的写入与读取。"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import DailyRecord, User
from app.services.clock import utc_now
from app.services.scoring import clamp_minutes, compute_deviation


def get_record(db: Session, user_id: int, record_date: date) -> DailyRecord | None:
    return db.scalar(
        select(DailyRecord).where(
            DailyRecord.user_id == user_id, DailyRecord.record_date == record_date
        )
    )


def list_records(
    db: Session,
    user_id: int,
    start: date | None = None,
    end: date | None = None,
) -> list[DailyRecord]:
    stmt = select(DailyRecord).where(DailyRecord.user_id == user_id)
    if start is not None:
        stmt = stmt.where(DailyRecord.record_date >= start)
    if end is not None:
        stmt = stmt.where(DailyRecord.record_date <= end)
    return list(db.scalars(stmt.order_by(DailyRecord.record_date)))


def resolve_target_minutes(
    user: User, existing: DailyRecord | None, record_date: date, today: date
) -> int:
    """决定这条记录该用哪个达标值。

    规则：**今天的记录是「活的」，过去的记录是「存档」。**

    - 新建记录      → 快照当前设置的达标值
    - 改今天的记录  → 重新快照（你刚调完目标就想让今天生效，符合直觉）
    - 改历史记录    → 保留它原本的达标值，绝不被现在的设置改写

    没有这条规则，调一次目标就会把全部历史偏差值静默重算。
    """
    if existing is None or record_date == today:
        return user.target_minutes
    return existing.target_minutes


def upsert_daily_record(
    db: Session,
    user: User,
    record_date: date,
    actual_minutes: int,
    today: date,
    note: str | None = None,
) -> DailyRecord:
    """写入或更新某天的打卡，并同时落库「当时的目标」和「当时的偏差」。"""
    actual_minutes = clamp_minutes(actual_minutes)
    note = (note or "").strip() or None

    existing = get_record(db, user.id, record_date)
    target = resolve_target_minutes(user, existing, record_date, today)
    deviation = compute_deviation(actual_minutes, target)

    if existing is None:
        record = DailyRecord(
            user_id=user.id,
            record_date=record_date,
            actual_minutes=actual_minutes,
            target_minutes=target,
            deviation_minutes=deviation,
            note=note,
        )
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            # 极少见：同一用户同一天的两次提交撞上唯一约束。退回成更新。
            db.rollback()
            existing = get_record(db, user.id, record_date)
            if existing is None:
                raise
            return upsert_daily_record(
                db, user, record_date, actual_minutes, today, note
            )
        db.refresh(record)
        return record

    existing.actual_minutes = actual_minutes
    existing.target_minutes = target
    existing.deviation_minutes = deviation
    existing.note = note
    existing.updated_at = utc_now()
    db.commit()
    db.refresh(existing)
    return existing


def apply_target_change(
    db: Session, user: User, new_target_minutes: int, today: date
) -> None:
    """修改达标值。

    只有「今天」那条记录会跟着重算——它还是活的。历史记录保持各自存档时
    的目标与偏差，一行都不动。这是 target 快照设计想保证的性质。
    """
    user.target_minutes = clamp_minutes(new_target_minutes)

    todays_record = get_record(db, user.id, today)
    if todays_record is not None:
        todays_record.target_minutes = user.target_minutes
        todays_record.deviation_minutes = compute_deviation(
            todays_record.actual_minutes, user.target_minutes
        )
        todays_record.updated_at = utc_now()

    db.commit()
