"""事件的增删改查。"""

from datetime import date, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, User
from app.services.clock import utc_now

# 事件配色，给界面上的下拉框用
EVENT_COLORS = {
    "slate": "默认",
    "rose": "粉",
    "amber": "橙",
    "emerald": "绿",
    "sky": "蓝",
    "violet": "紫",
}
DEFAULT_COLOR = "slate"


class EventValidationError(ValueError):
    """表单校验失败。路由把它翻译成给用户看的提示。"""


def parse_optional_time(raw: str | None) -> time | None:
    """表单里的 "HH:MM"。空字符串表示全天事件，不是错误。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return time.fromisoformat(raw)
    except ValueError as exc:
        raise EventValidationError(f"时间格式不对：{raw}") from exc


def _validate(title: str, start_time: time | None, end_time: time | None) -> str:
    title = (title or "").strip()
    if not title:
        raise EventValidationError("标题不能为空")
    if end_time and not start_time:
        raise EventValidationError("填了结束时间就得填开始时间")
    if start_time and end_time and end_time < start_time:
        raise EventValidationError("结束时间不能早于开始时间")
    return title


def list_events(
    db: Session, start: date | None = None, end: date | None = None
) -> list[Event]:
    stmt = select(Event)
    if start is not None:
        stmt = stmt.where(Event.event_date >= start)
    if end is not None:
        stmt = stmt.where(Event.event_date <= end)
    return list(
        db.scalars(stmt.order_by(Event.event_date.desc(), Event.start_time))
    )


def get_event(db: Session, event_id: int) -> Event | None:
    return db.get(Event, event_id)


def create_event(
    db: Session,
    user: User,
    title: str,
    event_date: date,
    description: str | None = None,
    start_time: time | None = None,
    end_time: time | None = None,
    color: str = DEFAULT_COLOR,
) -> Event:
    title = _validate(title, start_time, end_time)
    event = Event(
        created_by=user.id,
        title=title,
        description=(description or "").strip() or None,
        event_date=event_date,
        start_time=start_time,
        end_time=end_time,
        color=color if color in EVENT_COLORS else DEFAULT_COLOR,
        is_shared=True,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def update_event(
    db: Session,
    event: Event,
    title: str,
    event_date: date,
    description: str | None = None,
    start_time: time | None = None,
    end_time: time | None = None,
    color: str = DEFAULT_COLOR,
) -> Event:
    """两人都能改对方建的事件——这是共享日历，不是各自的私有日程。"""
    event.title = _validate(title, start_time, end_time)
    event.description = (description or "").strip() or None
    event.event_date = event_date
    event.start_time = start_time
    event.end_time = end_time
    event.color = color if color in EVENT_COLORS else DEFAULT_COLOR
    event.updated_at = utc_now()
    db.commit()
    db.refresh(event)
    return event


def delete_event(db: Session, event: Event) -> None:
    db.delete(event)
    db.commit()


def format_time_range(event: Event) -> str:
    """"14:00 – 15:30" / "14:00 起" / "全天"。"""
    if event.start_time is None:
        return "全天"
    start = event.start_time.strftime("%H:%M")
    if event.end_time is None:
        return f"{start} 起"
    return f"{start} – {event.end_time.strftime('%H:%M')}"
