"""把打卡记录和事件组装成 FullCalendar 能直接吃的事件数组。

FullCalendar 的约定：``allDay`` 事件用 ``YYYY-MM-DD``，定时事件用
``YYYY-MM-DDTHH:MM:SS``；``end`` 对全天事件是开区间，单日事件直接省略。
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    METRIC_EXERCISE,
    METRIC_SLEEP,
    DailyRecord,
    Event,
    ImageAsset,
    User,
)
from app.services.images import KIND_EVENT
from app.services.events import format_time_range, list_events
from app.services.records import list_records

# 指标图标。两人各记一个指标，图标本身就能区分是谁。
METRIC_ICONS = {METRIC_SLEEP: "😴", METRIC_EXERCISE: "💪"}

# 达标 / 未达标用颜色区分，比靠文字扫得快
COLOR_ON_TARGET = "#10b981"  # emerald
COLOR_OFF_TARGET = "#f59e0b"  # amber

EVENT_HEX = {
    "slate": "#64748b",
    "rose": "#f43f5e",
    "amber": "#f59e0b",
    "emerald": "#10b981",
    "sky": "#0ea5e9",
    "violet": "#8b5cf6",
}
EVENT_FALLBACK_HEX = EVENT_HEX["slate"]


def compact_duration(minutes: int) -> str:
    """日历格子里空间很小，用 "7:30" / "55m" 这种紧凑写法。"""
    hours, mins = divmod(abs(int(minutes)), 60)
    if hours:
        return f"{hours}:{mins:02d}"
    return f"{mins}m"


def record_to_feed_item(record: DailyRecord, user: User) -> dict:
    icon = METRIC_ICONS.get(user.metric_type, "•")
    mark = "✓" if record.on_target else "✗"
    return {
        "id": f"record-{record.id}",
        "title": f"{icon} {compact_duration(record.actual_minutes)} {mark}",
        "start": record.record_date.isoformat(),
        "allDay": True,
        "color": COLOR_ON_TARGET if record.on_target else COLOR_OFF_TARGET,
        "extendedProps": {
            "kind": "record",
            "who": user.display_name,
            "metric": user.metric_label,
            "actual_minutes": record.actual_minutes,
            "target_minutes": record.target_minutes,
            "deviation_minutes": record.deviation_minutes,
            "note": record.note,
        },
    }


def event_to_feed_item(event: Event, image_count: int = 0) -> dict:
    item = {
        "id": f"event-{event.id}",
        "title": f"📌 {event.title}" + (f" 📷{image_count}" if image_count else ""),
        "color": EVENT_HEX.get(event.color or "", EVENT_FALLBACK_HEX),
        "extendedProps": {
            "kind": "event",
            "event_id": event.id,
            "description": event.description,
            "when": format_time_range(event),
            "image_count": image_count,
        },
    }

    if event.start_time is None:
        item["start"] = event.event_date.isoformat()
        item["allDay"] = True
    else:
        item["start"] = f"{event.event_date.isoformat()}T{event.start_time.isoformat()}"
        item["allDay"] = False
        if event.end_time is not None:
            item["end"] = f"{event.event_date.isoformat()}T{event.end_time.isoformat()}"

    return item


def _image_counts(db: Session) -> dict[int, int]:
    """事件 id → 图片张数。一次分组查询，避免每个事件查一遍。"""
    rows = db.execute(
        select(ImageAsset.event_id, func.count())
        .where(ImageAsset.kind == KIND_EVENT, ImageAsset.event_id.isnot(None))
        .group_by(ImageAsset.event_id)
    ).all()
    return {event_id: count for event_id, count in rows}


def build_feed(db: Session, start: date | None, end: date | None) -> list[dict]:
    """区间内两人的全部打卡 + 全部事件。"""
    feed: list[dict] = []

    for user in db.scalars(select(User).order_by(User.id)):
        feed.extend(
            record_to_feed_item(record, user)
            for record in list_records(db, user.id, start, end)
        )

    counts = _image_counts(db)
    feed.extend(
        event_to_feed_item(event, counts.get(event.id, 0))
        for event in list_events(db, start, end)
    )

    return feed
