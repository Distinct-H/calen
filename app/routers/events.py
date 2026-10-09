"""事件页面与增删改。

用普通表单 + 303 跳转，不用 HTMX：事件是整页列表，局部刷新没好处，
而且纯表单在 JS 失效时照样能用。
"""

from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.models import User
from app.services.clock import today_in
from app.services.events import (
    EVENT_COLORS,
    DEFAULT_COLOR,
    EventValidationError,
    create_event,
    delete_event,
    format_time_range,
    get_event,
    list_events,
    parse_optional_time,
    update_event,
)
from app.templating import templates

router = APIRouter(include_in_schema=False)


def _back(message: str | None = None, error: str | None = None) -> RedirectResponse:
    query = ""
    if message:
        query = f"?message={quote(message)}"
    elif error:
        query = f"?error={quote(error)}"
    return RedirectResponse(f"/events{query}", status_code=303)


@router.get("/events")
def events_page(
    request: Request,
    edit: int | None = None,
    message: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    editing = get_event(db, edit) if edit else None
    if edit and editing is None:
        return _back(error="那条事件已经不存在了")

    return templates.TemplateResponse(
        request,
        "events.html",
        {
            "user": user,
            "events": list_events(db),
            "editing": editing,
            "today": today_in(user.timezone),
            "colors": EVENT_COLORS,
            "default_color": DEFAULT_COLOR,
            "format_time_range": format_time_range,
            "message": message,
            "error": error,
        },
    )


@router.post("/events")
def create(
    title: str = Form(...),
    event_date: date = Form(...),
    start_time: str = Form(""),
    end_time: str = Form(""),
    description: str = Form(""),
    color: str = Form(DEFAULT_COLOR),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    try:
        create_event(
            db=db,
            user=user,
            title=title,
            event_date=event_date,
            description=description,
            start_time=parse_optional_time(start_time),
            end_time=parse_optional_time(end_time),
            color=color,
        )
    except EventValidationError as exc:
        return _back(error=str(exc))
    return _back(message="事件已添加")


@router.post("/events/{event_id}")
def update(
    event_id: int,
    title: str = Form(...),
    event_date: date = Form(...),
    start_time: str = Form(""),
    end_time: str = Form(""),
    description: str = Form(""),
    color: str = Form(DEFAULT_COLOR),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    event = get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在")

    try:
        update_event(
            db=db,
            event=event,
            title=title,
            event_date=event_date,
            description=description,
            start_time=parse_optional_time(start_time),
            end_time=parse_optional_time(end_time),
            color=color,
        )
    except EventValidationError as exc:
        return _back(error=str(exc))
    return _back(message="事件已更新")


@router.post("/events/{event_id}/delete")
def remove(
    event_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    event = get_event(db, event_id)
    if event is None:
        # 重复提交删除不该报错
        return _back(message="事件已删除")
    delete_event(db, event)
    return _back(message="事件已删除")
