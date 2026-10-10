"""亲亲兑换规则的配置。挂在设置页下面。"""

from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.models import ROLE_MALE, User
from app.services.clock import today_in
from app.services.kisses import (
    KISS_SCALE,
    MODE_LABELS,
    apply_config_change,
    create_kiss_request,
    resettle_all,
    review_kiss_request,
)

router = APIRouter(include_in_schema=False)


def _back(message: str | None = None, error: str | None = None) -> RedirectResponse:
    query = ""
    if message:
        query = f"?message={quote(message)}"
    elif error:
        query = f"?error={quote(error)}"
    return RedirectResponse(f"/settings{query}", status_code=303)


def _today_back(message: str | None = None, error: str | None = None) -> RedirectResponse:
    query = ""
    if message:
        query = f"?message={quote(message)}"
    elif error:
        query = f"?error={quote(error)}"
    return RedirectResponse(f"/{query}", status_code=303)


@router.post("/kisses/requests")
def request_kisses(
    amount: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if user.role != ROLE_MALE:
        return _today_back(error="只有男生可以申请增加亲亲")
    try:
        amount_value = Decimal(amount.strip())
        if not amount_value.is_finite() or amount_value <= 0 or amount_value > 100:
            raise ValueError("申请数量需大于 0 且不超过 100 个")
        scaled_amount = amount_value * KISS_SCALE
        if scaled_amount != scaled_amount.to_integral_value():
            raise ValueError("申请数量最多保留两位小数")
        amount_centi = int(scaled_amount)
        create_kiss_request(
            db, user, today_in(user.timezone), amount_centi, note
        )
    except InvalidOperation:
        return _today_back(error="请输入有效的亲亲数量")
    except ValueError as exc:
        return _today_back(error=str(exc))
    return _today_back(message="申请已提交，等待女生审批")


@router.post("/kisses/requests/{request_id}/approve")
def approve_kiss_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    try:
        review_kiss_request(
            db, user, request_id, approve=True, today=today_in(user.timezone)
        )
    except (LookupError, ValueError) as exc:
        return _today_back(error=str(exc))
    return _today_back(message="已通过申请，亲亲已计入账本")


@router.post("/kisses/requests/{request_id}/reject")
def reject_kiss_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    try:
        review_kiss_request(
            db, user, request_id, approve=False, today=today_in(user.timezone)
        )
    except (LookupError, ValueError) as exc:
        return _today_back(error=str(exc))
    return _today_back(message="已拒绝申请")


@router.post("/settings/kisses")
def save_kiss_config(
    minutes_per_kiss: int = Form(..., ge=1, le=600),
    female_lead_mode: str = Form(...),
    custom_reward_name: str = Form("小红花"),
    minutes_per_custom_unit: int = Form(3, ge=1, le=600),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if female_lead_mode not in MODE_LABELS:
        return _back(error="女生领先的处理方式不对")

    apply_config_change(
        db=db,
        today=today_in(user.timezone),
        minutes_per_kiss=minutes_per_kiss,
        female_lead_mode=female_lead_mode,
        custom_reward_name=custom_reward_name,
        minutes_per_custom_unit=minutes_per_custom_unit,
    )
    return _back(
        message="兑换规则已保存。历史结算保留原比率不变，只有今天会重算。"
    )


@router.post("/settings/kisses/resettle")
def resettle(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """给还没结算过的历史日期补算。

    已有结算的日期会沿用它原本的比率，不会被当前配置改写。
    """
    count = resettle_all(db, today_in(user.timezone))
    return _back(message=f"已结算 {count} 天")
