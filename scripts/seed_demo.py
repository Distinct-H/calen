#!/usr/bin/env python3
"""灌入演示数据，方便看日历颜色和趋势图的效果。

    python scripts/seed_demo.py --days 45

只会写入「还没有记录」的日期，不会覆盖你真实填过的数据。
加 --reset 可以先清空所有打卡（仅限本地开发，会真的删数据）。
"""

import argparse
import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import METRIC_EXERCISE, METRIC_SLEEP, DailyRecord, User  # noqa: E402
from app.services.clock import today_in  # noqa: E402
from app.services.records import get_record  # noqa: E402
from app.services.scoring import clamp_minutes, compute_deviation  # noqa: E402

# 每种指标的拟真分布：(均值, 标准差) 分钟
DISTRIBUTION = {
    METRIC_SLEEP: (450, 70),  # 睡眠 7.5h 左右波动
    METRIC_EXERCISE: (55, 30),  # 锻炼 55min 左右波动，偶尔偷懒
}

NOTES = [
    None, None, None,  # 多数天没有备注
    "加班到很晚", "周末补觉", "跑了 5 公里", "去健身房了", "下雨没出门", "追剧了",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="灌入演示打卡数据")
    parser.add_argument("--days", type=int, default=45, help="往前灌多少天")
    parser.add_argument("--reset", action="store_true", help="先清空全部打卡记录")
    parser.add_argument("--seed", type=int, default=42, help="随机种子，便于复现")
    args = parser.parse_args()

    random.seed(args.seed)

    with SessionLocal() as db:
        users = list(db.scalars(select(User).order_by(User.id)))
        if not users:
            print("还没有账号。先跑 scripts/create_users.py")
            return 1

        if args.reset:
            db.execute(delete(DailyRecord))
            db.commit()
            print("已清空原有打卡记录")

        created = skipped = 0

        for user in users:
            mean, stdev = DISTRIBUTION.get(user.metric_type, (60, 20))
            today = today_in(user.timezone)

            for offset in range(args.days):
                day = today - timedelta(days=offset)

                if get_record(db, user.id, day) is not None:
                    skipped += 1
                    continue

                # 偶尔漏打卡，这样「连续达标」和日历空洞才看得出效果
                if random.random() < 0.12:
                    continue

                actual = clamp_minutes(int(random.gauss(mean, stdev)))
                db.add(
                    DailyRecord(
                        user_id=user.id,
                        record_date=day,
                        actual_minutes=actual,
                        # 演示数据统一用当前达标值作为快照
                        target_minutes=user.target_minutes,
                        deviation_minutes=compute_deviation(
                            actual, user.target_minutes
                        ),
                        note=random.choice(NOTES),
                    )
                )
                created += 1

        db.commit()

    print(f"已写入 {created} 条，跳过已存在的 {skipped} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
