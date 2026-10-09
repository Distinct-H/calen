"""定时触发端点。

刻意不把调度器塞进应用进程：Render 免费版闲置 15 分钟就休眠，
进程内的 APScheduler 根本不会触发。改成由外部按时来打这个端点，
谁来打都行（平台 cron、cron-job.org、手动 curl），重复打也安全。

    curl -X POST https://你的域名/internal/cron/tick -H "X-Cron-Secret: ..."
"""

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.services.reminder import run_due_reminders

router = APIRouter(prefix="/internal/cron", include_in_schema=False)


def _verify(provided: str | None) -> None:
    """compare_digest 做常量时间比较，避免用响应时间逐字节猜密钥。"""
    if not secrets.compare_digest(provided or "", settings.cron_secret):
        raise HTTPException(status_code=401, detail="X-Cron-Secret 不正确")


@router.post("/tick")
def tick(
    dry_run: bool = False,
    x_cron_secret: str | None = Header(None, alias="X-Cron-Secret"),
    db: Session = Depends(get_db),
):
    """发送此刻所有到期且今天还没发过的提醒。

    ``?dry_run=true`` 只报告会发什么，不真的推送、也不占用当天名额。
    """
    _verify(x_cron_secret)
    return run_due_reminders(db, dry_run=dry_run)
