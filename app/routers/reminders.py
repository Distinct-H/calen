"""推送渠道配置与提醒规则管理。都挂在设置页下面。"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.models import Reminder, User
from app.services.notifier import (
    PROVIDER_LABELS,
    NotifyError,
    build_notifier,
)
from app.services.reminder import KIND_LABELS, parse_cron_time

router = APIRouter(include_in_schema=False)


def _back(message: str | None = None, error: str | None = None) -> RedirectResponse:
    query = ""
    if message:
        query = f"?message={quote(message)}"
    elif error:
        query = f"?error={quote(error)}"
    return RedirectResponse(f"/settings{query}", status_code=303)


@router.post("/settings/push")
def save_push(
    push_provider: str = Form(""),
    push_token: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    provider = push_provider.strip()
    token = push_token.strip()

    if not provider:
        user.push_provider = None
        user.push_token = None
        db.commit()
        return _back(message="已关闭推送（站内提醒仍然有效）")

    if provider not in PROVIDER_LABELS:
        return _back(error="不支持的推送渠道")
    if not token:
        return _back(error="请填写推送密钥")

    user.push_provider = provider
    user.push_token = token
    db.commit()
    return _back(message="推送配置已保存，建议点一下「发送测试」确认能收到")


@router.post("/settings/push/test")
def test_push(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    notifier = build_notifier(user)
    if notifier is None:
        return _back(error="还没配置推送渠道")

    try:
        notifier.send(
            "测试推送",
            f"{user.display_name}，能看到这条就说明推送通了 ✓",
        )
    except NotifyError as exc:
        return _back(error=f"推送失败：{exc}")
    return _back(message="测试推送已发出，看看手机收到了没")


@router.post("/reminders")
def create_reminder(
    kind: str = Form(...),
    title: str = Form(""),
    cron_time: str = Form("21:00"),
    for_both: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if kind not in KIND_LABELS:
        return _back(error="不支持的提醒类型")
    if parse_cron_time(cron_time) is None:
        return _back(error="时间格式应为 HH:MM")

    db.add(
        Reminder(
            # 留空表示两人都提醒
            user_id=None if for_both else user.id,
            kind=kind,
            title=title.strip() or KIND_LABELS[kind],
            cron_time=cron_time.strip(),
            enabled=True,
        )
    )
    db.commit()
    return _back(message="提醒已添加")


@router.post("/reminders/{reminder_id}/toggle")
def toggle_reminder(
    reminder_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    reminder = db.get(Reminder, reminder_id)
    if reminder is None:
        return _back(error="提醒不存在")
    reminder.enabled = not reminder.enabled
    db.commit()
    return _back(message="已启用" if reminder.enabled else "已停用")


@router.post("/reminders/{reminder_id}/delete")
def delete_reminder(
    reminder_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    reminder = db.get(Reminder, reminder_id)
    if reminder is not None:
        db.delete(reminder)
        db.commit()
    return _back(message="提醒已删除")
