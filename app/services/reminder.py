"""提醒的筛选与幂等发送。

调度不写在应用进程里：这里只提供一个「把此刻该发的都发掉」的函数，
由 /internal/cron/tick 触发。谁来打这个端点（平台 cron、外部 cron、
手动 curl）都无所谓，重复打也安全。

**幂等机制**：先往 reminder_logs 抢占 (reminder, user, date) 这一行，
抢到了才真的推送。唯一约束让并发/重复调用必然只有一个抢得到。

**失败不重试**：推送失败会把该行记成 failed 且当天不再尝试。
这是刻意的取舍——重试就得面对「请求超时但其实发成功了」的情况，
那会导致重复打扰。宁可漏一条，也不要一天响五次。
"""

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Reminder, ReminderLog, User
from app.services.anniversary import build_views
from app.services.clock import now_in, utc_now
from app.services.notifier import NotifyError, build_notifier
from app.services.records import get_record

KIND_DAILY_CHECKIN = "daily_checkin"
KIND_ANNIVERSARY = "anniversary"
KIND_CUSTOM = "custom"

KIND_LABELS = {
    KIND_DAILY_CHECKIN: "打卡提醒（当天已填就不发）",
    KIND_ANNIVERSARY: "纪念日临近提醒",
    KIND_CUSTOM: "自定义提醒",
}

STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


@dataclass
class Outcome:
    reminder_id: int
    user_id: int
    status: str
    detail: str = ""


def parse_cron_time(raw: str) -> time | None:
    try:
        return time.fromisoformat(raw.strip())
    except (ValueError, AttributeError):
        return None


def list_reminders(db: Session) -> list[Reminder]:
    return list(db.scalars(select(Reminder).order_by(Reminder.cron_time, Reminder.id)))


def targets_of(db: Session, reminder: Reminder) -> list[User]:
    """user_id 为空表示两人都提醒。"""
    if reminder.user_id is not None:
        user = db.get(User, reminder.user_id)
        return [user] if user else []
    return list(db.scalars(select(User).order_by(User.id)))


def build_message(
    db: Session, reminder: Reminder, user: User, local_date: date
) -> tuple[str, str] | None:
    """生成 (标题, 正文)。返回 None 表示此刻没有提醒的必要。"""
    if reminder.kind == KIND_DAILY_CHECKIN:
        if get_record(db, user.id, local_date) is not None:
            return None  # 已经填了，不打扰
        return (
            reminder.title or "今天还没打卡",
            f"{user.display_name}，{user.metric_label}还没记录。"
            f"达标值 {user.target_minutes // 60} 小时 {user.target_minutes % 60} 分。",
        )

    if reminder.kind == KIND_ANNIVERSARY:
        upcoming = [v for v in build_views(db, local_date) if v.should_remind]
        if not upcoming:
            return None
        lines = [f"· {v.anniversary.title} —— {v.countdown_text}" for v in upcoming]
        return (reminder.title or "纪念日提醒", "\n".join(lines))

    return (reminder.title or "提醒", reminder.title or "")


def _claim(
    db: Session, reminder: Reminder, user: User, local_date: date
) -> ReminderLog | None:
    """抢占当天的发送名额。抢不到说明已经发过了。"""
    log = ReminderLog(
        reminder_id=reminder.id,
        user_id=user.id,
        sent_date=local_date,
        status="pending",
    )
    db.add(log)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return log


def run_due_reminders(db: Session, dry_run: bool = False) -> dict:
    """把此刻所有到期且今天还没发过的提醒发掉。

    「到期」= 按用户本地时间，今天的 cron_time 已经过了。
    服务停了半天再恢复时也会补发（晚发好过不发），但一天仍然只发一次。
    """
    outcomes: list[Outcome] = []

    reminders = list(db.scalars(select(Reminder).where(Reminder.enabled.is_(True))))

    for reminder in reminders:
        scheduled = parse_cron_time(reminder.cron_time)
        if scheduled is None:
            outcomes.append(
                Outcome(reminder.id, 0, STATUS_SKIPPED, f"时间格式不对：{reminder.cron_time}")
            )
            continue

        for user in targets_of(db, reminder):
            local_now = now_in(user.timezone)
            local_date = local_now.date()

            if local_now.time() < scheduled:
                outcomes.append(Outcome(reminder.id, user.id, STATUS_SKIPPED, "还没到点"))
                continue

            message = build_message(db, reminder, user, local_date)
            if message is None:
                outcomes.append(
                    Outcome(reminder.id, user.id, STATUS_SKIPPED, "当前无需提醒")
                )
                continue

            notifier = build_notifier(user)
            if notifier is None:
                outcomes.append(
                    Outcome(reminder.id, user.id, STATUS_SKIPPED, "未配置推送渠道")
                )
                continue

            if dry_run:
                outcomes.append(
                    Outcome(reminder.id, user.id, "would_send", message[0])
                )
                continue

            log = _claim(db, reminder, user, local_date)
            if log is None:
                outcomes.append(
                    Outcome(reminder.id, user.id, STATUS_SKIPPED, "今天已经发过")
                )
                continue

            title, body = message
            try:
                notifier.send(title, body)
            except NotifyError as exc:
                log.status = STATUS_FAILED
                log.error = str(exc)[:500]
                db.commit()
                outcomes.append(Outcome(reminder.id, user.id, STATUS_FAILED, str(exc)))
                continue

            log.status = STATUS_SENT
            log.sent_at = utc_now()
            db.commit()
            outcomes.append(Outcome(reminder.id, user.id, STATUS_SENT, title))

    sent = sum(1 for o in outcomes if o.status == STATUS_SENT)
    failed = sum(1 for o in outcomes if o.status == STATUS_FAILED)

    return {
        "sent": sent,
        "failed": failed,
        "total_checked": len(outcomes),
        "outcomes": [
            {
                "reminder_id": o.reminder_id,
                "user_id": o.user_id,
                "status": o.status,
                "detail": o.detail,
            }
            for o in outcomes
        ],
    }


def in_app_hints(db: Session, user: User, local_date: date) -> list[str]:
    """站内提醒横幅的文案。不依赖推送配置，打开网页就能看到。"""
    hints: list[str] = []

    if get_record(db, user.id, local_date) is None:
        hints.append(f"今天的{user.metric_label}还没记录")

    for view in build_views(db, local_date):
        if view.should_remind:
            hints.append(f"{view.anniversary.title} —— {view.countdown_text}")

    return hints
