"""每日打卡。

HTML 端点（``/records/...``）返回 HTMX 片段，JSON 端点（``/api/records``）
给后面的日历和图表用。
"""

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import get_partner, require_user
from app.db import get_db
from app.models import User
from app.services.clock import today_in
from app.services.dashboard import build_dashboard
from app.services.records import list_records, upsert_daily_record
from app.services.scoring import to_minutes
from app.templating import templates

router = APIRouter(tags=["records"])


@router.post("/records")
def submit_record(
    request: Request,
    hours: int = Form(0, ge=0, le=24),
    minutes: int = Form(0, ge=0, le=59),
    note: str = Form(""),
    record_date: date | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """提交打卡，返回重新渲染的今日面板（HTMX 局部刷新）。"""
    today = today_in(user.timezone)
    target_date = record_date or today

    if target_date > today:
        raise HTTPException(status_code=400, detail="不能给未来的日期打卡")

    upsert_daily_record(
        db=db,
        user=user,
        record_date=target_date,
        actual_minutes=to_minutes(hours, minutes),
        today=today,
        note=note,
    )

    return templates.TemplateResponse(
        request,
        "partials/today_panel.html",
        {"view": build_dashboard(db, user), "user": user, "saved": True},
    )


@router.get("/api/records")
def api_list_records(
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """两人在区间内的全部打卡。日历和统计页取数用。"""
    people = [user]
    partner = get_partner(db, user)
    if partner:
        people.append(partner)

    return {
        "people": [
            {
                "user_id": person.id,
                "display_name": person.display_name,
                "role": person.role,
                "metric_type": person.metric_type,
                "records": [
                    {
                        "date": record.record_date.isoformat(),
                        "actual_minutes": record.actual_minutes,
                        "target_minutes": record.target_minutes,
                        "deviation_minutes": record.deviation_minutes,
                        "on_target": record.on_target,
                        "note": record.note,
                    }
                    for record in list_records(db, person.id, start, end)
                ],
            }
            for person in people
        ]
    }
