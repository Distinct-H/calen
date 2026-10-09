"""日历页与 FullCalendar 的事件数据源。"""

from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.models import User
from app.services.calendar import build_feed
from app.services.clock import today_in
from app.templating import templates

router = APIRouter()


def _parse_bound(value: str | None) -> date | None:
    """FullCalendar 传来的可能是 "2026-10-01"，也可能带时间和时区偏移。

    取前 10 位当日期即可；解析不了就按「不限制区间」处理，宁可多返回也不要 500。
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


@router.get("/calendar", include_in_schema=False)
def calendar_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse(
        request,
        "calendar.html",
        {"user": user, "today": today_in(user.timezone)},
    )


@router.get("/api/calendar")
def calendar_feed(
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    return build_feed(db, _parse_bound(start), _parse_bound(end))
