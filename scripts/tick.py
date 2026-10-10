#!/usr/bin/env python3
"""把此刻到期的提醒发掉。平台 cron 用这个入口，不走 HTTP。

    python scripts/tick.py            # 真的发
    python scripts/tick.py --dry-run  # 只看会发什么

和 POST /internal/cron/tick 调的是同一个函数，共用同一套幂等保证，
所以两边同时配着也不会重复推送。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal  # noqa: E402
from app.services.reminder import run_due_reminders  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="发送到期提醒")
    parser.add_argument("--dry-run", action="store_true", help="只报告，不真的推送")
    parser.add_argument("--quiet", action="store_true", help="只输出汇总")
    args = parser.parse_args()

    with SessionLocal() as db:
        result = run_due_reminders(db, dry_run=args.dry_run)

    if args.quiet:
        print(f"sent={result['sent']} failed={result['failed']}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # 推送失败时返回非 0，方便平台把这次 cron 标成失败并告警
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
