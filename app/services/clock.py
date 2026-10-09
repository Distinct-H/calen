"""时区与「今天是哪天」。

托管平台的容器跑在 UTC。如果直接用服务器日期，中国时间凌晨 0:00–8:00
的打卡会被记到前一天——这是这类应用最常见的隐性 bug，所以所有
「今天」「该不该发提醒」一律走这里，按用户自己的时区算。
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings


def resolve_zone(tz_name: str | None) -> ZoneInfo:
    """拿不到有效时区时退回默认时区，而不是让请求 500。"""
    for candidate in (tz_name, settings.default_timezone, "UTC"):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return ZoneInfo("UTC")


def now_in(tz_name: str | None) -> datetime:
    return datetime.now(resolve_zone(tz_name))


def today_in(tz_name: str | None) -> date:
    return now_in(tz_name).date()


def utc_now() -> datetime:
    return datetime.now(UTC)
