#!/usr/bin/env python3
"""清空业务数据，准备开始真实记录。

默认**保留账号**，只清打卡、亲亲结算、事件、纪念日、图片和提醒日志。

    python scripts/reset_data.py                 # 交互确认后清理
    python scripts/reset_data.py --yes           # 跳过确认
    python scripts/reset_data.py --keep-images   # 图片留着
    python scripts/reset_data.py --all --yes     # 连账号一起删（之后要重新建号）

三道安全栏：
1. **生产环境默认拒绝执行**（DEBUG=false 时要显式加 --force-production）
2. 本地 SQLite 会先自动备份整个库文件
3. 不加 --yes 时必须手敲确认词，回车略过不算
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Anniversary,
    DailyRecord,
    Event,
    ImageAsset,
    KissConfig,
    KissSettlement,
    Reminder,
    ReminderLog,
    User,
)

CONFIRM_WORD = "CLEAR"

# 按外键依赖顺序删：引用别人的先删
# （images 引用 users 和 events，reminder_logs 引用 reminders）
DELETE_ORDER = [
    ("提醒日志", ReminderLog),
    ("提醒规则", Reminder),
    ("图片", ImageAsset),
    ("事件", Event),
    ("纪念日", Anniversary),
    ("亲亲结算", KissSettlement),
    ("打卡记录", DailyRecord),
]


def backup_sqlite() -> Path | None:
    """本地 SQLite 先整库拷一份。删之前留条退路，成本几乎为零。"""
    prefix = "sqlite:///"
    url = settings.sqlalchemy_url
    if not url.startswith(prefix):
        return None

    source = Path(url[len(prefix) :]).expanduser()
    if not source.exists():
        return None

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = source.with_name(f"{source.stem}.backup_{stamp}{source.suffix}")
    shutil.copy2(source, target)
    return target


def summarize(db) -> dict[str, int]:
    counts = {label: db.query(model).count() for label, model in DELETE_ORDER}
    counts["账号"] = db.query(User).count()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="清空业务数据")
    parser.add_argument("--yes", action="store_true", help="跳过交互确认")
    parser.add_argument("--all", action="store_true", help="连账号一起删")
    parser.add_argument("--keep-images", action="store_true", help="保留图片")
    parser.add_argument(
        "--keep-config", action="store_true", help="保留亲亲兑换规则，不恢复默认值"
    )
    parser.add_argument(
        "--force-production",
        action="store_true",
        help="在 DEBUG=false 的环境上强制执行（危险）",
    )
    args = parser.parse_args()

    if not settings.debug and not args.force_production:
        print("拒绝执行：当前是生产配置（DEBUG=false）。")
        print("确定要清生产数据的话，先 pg_dump 备份，再加 --force-production。")
        return 1

    targets = [
        (label, model)
        for label, model in DELETE_ORDER
        if not (args.keep_images and model is ImageAsset)
    ]

    with SessionLocal() as db:
        before = summarize(db)

        print("当前数据：")
        for label, count in before.items():
            print(f"  {label:10} {count:>5} 条")

        will_clear = [label for label, model in targets if before[label]]
        print("\n将要清空：" + ("、".join(will_clear) if will_clear else "（没有数据）"))
        if args.all:
            print("并且删除全部账号 —— 清完需要重新跑 create_users.py")
        if args.keep_images:
            print("图片保留")
        if not args.keep_config:
            print("亲亲兑换规则恢复默认（3 分钟 : 1 个亲亲）")

        if not will_clear and not args.all:
            print("\n已经是干净的，什么都没做。")
            return 0

        if not args.yes:
            answer = input(f"\n确认请输入 {CONFIRM_WORD}（其他任何输入都会取消）: ").strip()
            if answer != CONFIRM_WORD:
                print("已取消，数据未改动。")
                return 1

        backup = backup_sqlite()
        if backup:
            print(f"\n已备份到 {backup}")

        for label, model in targets:
            db.execute(delete(model))

        if args.all:
            db.execute(delete(User))

        if not args.keep_config:
            db.execute(delete(KissConfig))

        db.commit()

        print("\n清理后：")
        for label, count in summarize(db).items():
            print(f"  {label:10} {count:>5} 条")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
