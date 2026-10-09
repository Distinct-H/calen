"""统计页与图表数据接口。"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.models import User
from app.services.clock import today_in
from app.services.stats import build_stats
from app.templating import templates

router = APIRouter()


@router.get("/stats", include_in_schema=False)
def stats_page(
    request: Request,
    days: int = 90,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "user": user,
            "stats": build_stats(db, today_in(user.timezone), days),
        },
    )


@router.get("/api/stats")
def api_stats(
    days: int = 90,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    return build_stats(db, today_in(user.timezone), days)
