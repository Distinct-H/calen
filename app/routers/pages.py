"""页面路由：登录、今日、设置。"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import (
    authenticate,
    get_optional_user,
    hash_password,
    login_session,
    logout_session,
    require_user,
    verify_password,
)
from app.db import get_db
from app.models import User
from app.services.clock import today_in
from app.services.dashboard import build_dashboard
from app.services.images import MAX_UPLOAD_BYTES, get_avatar, total_bytes
from app.services.kisses import MODE_LABELS, build_ledger
from app.services.notifier import PROVIDER_LABELS
from app.services.records import apply_target_change
from app.services.reminder import KIND_LABELS, in_app_hints, list_reminders
from app.services.scoring import split_minutes, to_minutes
from app.templating import templates

router = APIRouter(include_in_schema=False)


@router.get("/login")
def login_form(request: Request, user: User | None = Depends(get_optional_user)):
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = authenticate(db, username.strip(), password)
    if user is None:
        # 不区分「用户名不存在」和「密码错误」，避免泄露账号是否存在
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "用户名或密码不正确", "username": username},
            status_code=401,
        )
    login_session(request, user)
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    logout_session(request)
    return RedirectResponse("/login", status_code=303)


@router.get("/")
def today_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    view = build_dashboard(db, user)
    return templates.TemplateResponse(
        request,
        "today.html",
        {
            "view": view,
            "user": user,
            # 站内提醒：不依赖推送配置，打开页面就能看到
            "hints": in_app_hints(db, user, view.day),
        },
    )


@router.get("/settings")
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    message: str | None = None,
    error: str | None = None,
):
    target_hours, target_minutes = split_minutes(user.target_minutes)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "target_hours": target_hours,
            "target_minutes": target_minutes,
            "reminders": list_reminders(db),
            "reminder_kinds": KIND_LABELS,
            "push_providers": PROVIDER_LABELS,
            "avatar": get_avatar(db, user),
            "max_upload_mb": MAX_UPLOAD_BYTES // 1024 // 1024,
            "image_bytes": total_bytes(db),
            "ledger": build_ledger(db, today_in(user.timezone)),
            "kiss_modes": MODE_LABELS,
            "message": message,
            "error": error,
        },
    )


@router.post("/settings/profile")
def update_profile(
    display_name: str = Form(...),
    target_hours: int = Form(0, ge=0, le=24),
    target_minutes: int = Form(0, ge=0, le=59),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    new_target = to_minutes(target_hours, target_minutes)
    if new_target == 0:
        return RedirectResponse(
            "/settings?error=达标值不能为 0", status_code=303
        )

    user.display_name = display_name.strip() or user.display_name
    apply_target_change(db, user, new_target, today_in(user.timezone))

    return RedirectResponse(
        "/settings?message=已保存。历史记录的偏差值不受影响，只有今天会跟着重算。",
        status_code=303,
    )


@router.post("/settings/password")
def update_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if not verify_password(current_password, user.password_hash):
        return RedirectResponse("/settings?error=当前密码不正确", status_code=303)
    if len(new_password) < 8:
        return RedirectResponse("/settings?error=新密码至少 8 位", status_code=303)
    if new_password != confirm_password:
        return RedirectResponse("/settings?error=两次输入的新密码不一致", status_code=303)

    user.password_hash = hash_password(new_password)
    db.commit()
    return RedirectResponse("/settings?message=密码已更新", status_code=303)
