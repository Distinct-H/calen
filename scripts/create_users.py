#!/usr/bin/env python3
"""创建 / 更新账号。

这个应用刻意没有注册入口——只有两个用户，账号在这里建。
同一个用户名重复执行会更新资料，不会报错。

交互式：
    python scripts/create_users.py

带参数（适合写脚本或首次初始化）：
    python scripts/create_users.py --username her --display-name 小美 \
        --role female --target 8:00 --password '...'
"""

import argparse
import getpass
import sys
from pathlib import Path

# 支持直接 python scripts/create_users.py 运行，而不必先设 PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    METRIC_EXERCISE,
    METRIC_SLEEP,
    ROLE_FEMALE,
    ROLE_MALE,
    User,
)

# 默认的身份 → 指标映射，可用 --metric 覆盖
DEFAULT_METRIC = {ROLE_FEMALE: METRIC_SLEEP, ROLE_MALE: METRIC_EXERCISE}
DEFAULT_TARGET = {METRIC_SLEEP: 8 * 60, METRIC_EXERCISE: 60}


def parse_target(text: str) -> int:
    """接受 "8:00"、"8h30"、"480" 三种写法，统一返回分钟数。"""
    text = text.strip().lower().replace("h", ":").replace("小时", ":")
    if ":" in text:
        hours, _, minutes = text.partition(":")
        return int(hours or 0) * 60 + int(minutes or 0)
    return int(text)


def prompt_choice(label: str, choices: list[str]) -> str:
    while True:
        answer = input(f"{label} [{'/'.join(choices)}]: ").strip().lower()
        if answer in choices:
            return answer
        print(f"  只能填 {' 或 '.join(choices)}")


def prompt_password() -> str:
    while True:
        first = getpass.getpass("密码（至少 8 位，输入时不显示）: ")
        if len(first) < 8:
            print("  太短了，至少 8 位")
            continue
        if first != getpass.getpass("再输一次: "):
            print("  两次不一致，重来")
            continue
        return first


def main() -> int:
    parser = argparse.ArgumentParser(description="创建或更新账号")
    parser.add_argument("--username", help="登录用户名")
    parser.add_argument("--display-name", help="昵称")
    parser.add_argument("--role", choices=[ROLE_FEMALE, ROLE_MALE], help="身份")
    parser.add_argument(
        "--metric",
        choices=[METRIC_SLEEP, METRIC_EXERCISE],
        help="追踪指标，默认按身份推断（female→睡眠，male→锻炼）",
    )
    parser.add_argument("--target", help='达标值，如 "8:00" / "8h30" / "480"')
    parser.add_argument("--password", help="密码。不传则交互式输入（更安全）")
    parser.add_argument("--timezone", default=settings.default_timezone)
    args = parser.parse_args()

    username = args.username or input("用户名: ").strip()
    if not username:
        print("用户名不能为空")
        return 1

    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.username == username))

        if existing:
            print(f"账号 {username} 已存在，将更新资料（留空则保持不变）")

        role = args.role or (
            existing.role if existing else prompt_choice("身份", [ROLE_FEMALE, ROLE_MALE])
        )
        metric = args.metric or (
            existing.metric_type if existing else DEFAULT_METRIC[role]
        )
        display_name = (
            args.display_name
            or input(f"昵称{f' [{existing.display_name}]' if existing else ''}: ").strip()
            or (existing.display_name if existing else username)
        )

        default_target = existing.target_minutes if existing else DEFAULT_TARGET[metric]
        target_text = args.target or input(
            f"达标值（如 8:00）[{default_target // 60}:{default_target % 60:02d}]: "
        ).strip()
        target_minutes = parse_target(target_text) if target_text else default_target

        if args.password:
            password = args.password
        elif existing:
            raw = getpass.getpass("新密码（留空保持不变）: ")
            password = raw or None
        else:
            password = prompt_password()

        if existing:
            existing.display_name = display_name
            existing.role = role
            existing.metric_type = metric
            existing.target_minutes = target_minutes
            existing.timezone = args.timezone
            if password:
                existing.password_hash = hash_password(password)
            action = "已更新"
        else:
            db.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    display_name=display_name,
                    role=role,
                    metric_type=metric,
                    target_minutes=target_minutes,
                    timezone=args.timezone,
                )
            )
            action = "已创建"

        db.commit()

    print(
        f"{action}：{username}（{display_name}）"
        f" 身份={role} 指标={metric}"
        f" 达标={target_minutes // 60}:{target_minutes % 60:02d}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
