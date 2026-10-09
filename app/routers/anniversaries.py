"""纪念日页面与增删改。"""

from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.models import Anniversary, User
from app.services.anniversary import (
    RECURRENCE_LABELS,
    RECURRENCE_YEARLY,
    build_views,
)
from app.services.clock import today_in
from app.templating import templates

router = APIRouter(include_in_schema=False)


def _back(message: str | None = None, error: str | None = None) -> RedirectResponse:
    query = ""
    if message:
        query = f"?message={quote(message)}"
    elif error:
        query = f"?error={quote(error)}"
    return RedirectResponse(f"/anniversaries{query}", status_code=303)


@router.get("/anniversaries")
def anniversaries_page(
    request: Request,
    edit: int | None = None,
    message: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    editing = db.get(Anniversary, edit) if edit else None
    if edit and editing is None:
        return _back(error="那条纪念日已经不存在了")

    today = today_in(user.timezone)
    return templates.TemplateResponse(
        request,
        "anniversaries.html",
        {
            "user": user,
            "views": build_views(db, today),
            "editing": editing,
            "today": today,
            "recurrences": RECURRENCE_LABELS,
            "message": message,
            "error": error,
        },
    )


@router.post("/anniversaries")
def create(
    title: str = Form(...),
    start_date: date = Form(...),
    recurrence: str = Form(RECURRENCE_YEARLY),
    show_countup: bool = Form(False),
    remind_days_before: int = Form(3, ge=0, le=60),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    title = title.strip()
    if not title:
        return _back(error="标题不能为空")
    if recurrence not in RECURRENCE_LABELS:
        return _back(error="重复方式不对")

    db.add(
        Anniversary(
            title=title,
            start_date=start_date,
            recurrence=recurrence,
            show_countup=show_countup,
            remind_days_before=remind_days_before,
        )
    )
    db.commit()
    return _back(message="纪念日已添加")


@router.post("/anniversaries/{anniversary_id}")
def update(
    anniversary_id: int,
    title: str = Form(...),
    start_date: date = Form(...),
    recurrence: str = Form(RECURRENCE_YEARLY),
    show_countup: bool = Form(False),
    remind_days_before: int = Form(3, ge=0, le=60),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    anniversary = db.get(Anniversary, anniversary_id)
    if anniversary is None:
        raise HTTPException(status_code=404, detail="纪念日不存在")

    title = title.strip()
    if not title:
        return _back(error="标题不能为空")
    if recurrence not in RECURRENCE_LABELS:
        return _back(error="重复方式不对")

    anniversary.title = title
    anniversary.start_date = start_date
    anniversary.recurrence = recurrence
    anniversary.show_countup = show_countup
    anniversary.remind_days_before = remind_days_before
    db.commit()
    return _back(message="纪念日已更新")


@router.post("/anniversaries/{anniversary_id}/delete")
def remove(
    anniversary_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    anniversary = db.get(Anniversary, anniversary_id)
    if anniversary is not None:
        db.delete(anniversary)
        db.commit()
    return _back(message="纪念日已删除")
