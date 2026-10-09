"""提醒的筛选与幂等。

本文件的核心是 `test_second_tick_does_not_resend` ——
平台 cron 会重复触发、服务会重启，不幂等就会一天响好几次。
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.models import Anniversary, Reminder, ReminderLog
from app.services.notifier import NotifyError
from app.services.reminder import (
    KIND_ANNIVERSARY,
    KIND_DAILY_CHECKIN,
    STATUS_FAILED,
    STATUS_SENT,
    run_due_reminders,
)
from app.services.records import upsert_daily_record

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 9, 21, 30, tzinfo=TZ)
TODAY = date(2026, 10, 9)


class FakeNotifier:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = fail

    def send(self, title: str, body: str) -> None:
        if self.fail:
            raise NotifyError("模拟推送失败")
        self.sent.append((title, body))


@pytest.fixture
def frozen_clock(monkeypatch):
    """冻结时钟，否则测试结果会随运行时刻变化。"""
    monkeypatch.setattr("app.services.reminder.now_in", lambda _tz: NOW)


@pytest.fixture
def push(monkeypatch):
    notifier = FakeNotifier()
    monkeypatch.setattr("app.services.reminder.build_notifier", lambda _user: notifier)
    return notifier


def add_reminder(db, kind=KIND_DAILY_CHECKIN, cron_time="21:00", user_id=None):
    reminder = Reminder(
        user_id=user_id, kind=kind, title="该打卡了", cron_time=cron_time, enabled=True
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder


class TestIdempotency:
    def test_second_tick_does_not_resend(self, db, her, frozen_clock, push):
        """★ 连续触发两次，只能真的发一条。"""
        add_reminder(db, user_id=her.id)

        first = run_due_reminders(db)
        second = run_due_reminders(db)

        assert first["sent"] == 1
        assert second["sent"] == 0
        assert len(push.sent) == 1

    def test_log_row_records_the_send(self, db, her, frozen_clock, push):
        reminder = add_reminder(db, user_id=her.id)
        run_due_reminders(db)

        log = db.query(ReminderLog).one()
        assert log.reminder_id == reminder.id
        assert log.user_id == her.id
        assert log.sent_date == TODAY
        assert log.status == STATUS_SENT

    def test_failure_is_recorded_and_not_retried(self, db, her, frozen_clock, monkeypatch):
        """推送失败当天不再重试——重试会面对「超时但其实发出去了」的情况。"""
        broken = FakeNotifier(fail=True)
        monkeypatch.setattr("app.services.reminder.build_notifier", lambda _u: broken)
        add_reminder(db, user_id=her.id)

        first = run_due_reminders(db)
        second = run_due_reminders(db)

        assert first["failed"] == 1
        assert second["sent"] == 0 and second["failed"] == 0
        assert db.query(ReminderLog).one().status == STATUS_FAILED


class TestScheduling:
    def test_not_yet_due_is_skipped(self, db, her, frozen_clock, push):
        add_reminder(db, cron_time="23:00", user_id=her.id)
        assert run_due_reminders(db)["sent"] == 0
        assert push.sent == []

    def test_catches_up_after_downtime(self, db, her, frozen_clock, push):
        """早上 8 点的提醒，服务到晚上才恢复——晚发好过不发。"""
        add_reminder(db, cron_time="08:00", user_id=her.id)
        assert run_due_reminders(db)["sent"] == 1

    def test_disabled_reminder_is_ignored(self, db, her, frozen_clock, push):
        reminder = add_reminder(db, user_id=her.id)
        reminder.enabled = False
        db.commit()

        assert run_due_reminders(db)["sent"] == 0

    def test_malformed_time_does_not_crash(self, db, her, frozen_clock, push):
        add_reminder(db, cron_time="不是时间", user_id=her.id)
        result = run_due_reminders(db)
        assert result["sent"] == 0
        assert any("时间格式不对" in o["detail"] for o in result["outcomes"])

    def test_shared_reminder_notifies_both(self, db, her, him, frozen_clock, push):
        add_reminder(db, user_id=None)  # None = 两人都提醒
        assert run_due_reminders(db)["sent"] == 2
        assert len(push.sent) == 2


class TestDailyCheckin:
    def test_skipped_when_already_filled(self, db, her, frozen_clock, push):
        upsert_daily_record(db, her, TODAY, actual_minutes=450, today=TODAY)
        add_reminder(db, user_id=her.id)

        assert run_due_reminders(db)["sent"] == 0
        assert push.sent == []

    def test_message_mentions_the_metric(self, db, her, frozen_clock, push):
        add_reminder(db, user_id=her.id)
        run_due_reminders(db)

        _title, body = push.sent[0]
        assert "睡眠时长" in body
        assert "小美" in body


class TestAnniversaryReminder:
    def test_fires_inside_remind_window(self, db, her, frozen_clock, push):
        db.add(
            Anniversary(
                title="在一起",
                start_date=date(2020, 10, 11),
                recurrence="yearly",
                show_countup=True,
                remind_days_before=3,
            )
        )
        db.commit()
        add_reminder(db, kind=KIND_ANNIVERSARY, user_id=her.id)

        assert run_due_reminders(db)["sent"] == 1
        assert "在一起" in push.sent[0][1]

    def test_silent_outside_window(self, db, her, frozen_clock, push):
        db.add(
            Anniversary(
                title="还很远",
                start_date=date(2020, 12, 25),
                recurrence="yearly",
                show_countup=True,
                remind_days_before=3,
            )
        )
        db.commit()
        add_reminder(db, kind=KIND_ANNIVERSARY, user_id=her.id)

        assert run_due_reminders(db)["sent"] == 0


class TestDryRun:
    def test_dry_run_reports_without_sending_or_claiming(self, db, her, frozen_clock, push):
        add_reminder(db, user_id=her.id)

        preview = run_due_reminders(db, dry_run=True)
        assert any(o["status"] == "would_send" for o in preview["outcomes"])
        assert push.sent == []
        assert db.query(ReminderLog).count() == 0

        # 没占用名额，真的跑还是会发
        assert run_due_reminders(db)["sent"] == 1


class TestPushNotConfigured:
    def test_no_channel_means_no_send(self, db, her, frozen_clock):
        """没配推送渠道不该报错，站内提醒照常工作。"""
        add_reminder(db, user_id=her.id)
        result = run_due_reminders(db)
        assert result["sent"] == 0
        assert any("未配置推送渠道" in o["detail"] for o in result["outcomes"])


class TestCronEndpoint:
    def test_requires_secret(self, client):
        assert client.post("/internal/cron/tick").status_code == 401

    def test_wrong_secret_rejected(self, client):
        response = client.post(
            "/internal/cron/tick", headers={"X-Cron-Secret": "wrong"}
        )
        assert response.status_code == 401

    def test_correct_secret_accepted(self, client, her):
        response = client.post(
            "/internal/cron/tick", headers={"X-Cron-Secret": "test-only-cron-secret"}
        )
        assert response.status_code == 200
        assert "sent" in response.json()
