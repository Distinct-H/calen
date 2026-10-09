"""日历数据源与统计序列。"""

from datetime import date, time

from app.services.calendar import build_feed, compact_duration
from app.services.events import create_event
from app.services.records import upsert_daily_record
from app.services.stats import build_stats, date_range

DAY = date(2026, 10, 9)


class TestCompactDuration:
    def test_hours_and_minutes(self):
        assert compact_duration(450) == "7:30"

    def test_whole_hours(self):
        assert compact_duration(480) == "8:00"

    def test_under_an_hour(self):
        assert compact_duration(55) == "55m"


class TestCalendarFeed:
    def test_records_become_all_day_items(self, db, her, him):
        upsert_daily_record(db, her, DAY, actual_minutes=450, today=DAY)
        feed = build_feed(db, DAY, DAY)

        item = next(i for i in feed if i["extendedProps"]["kind"] == "record")
        assert item["allDay"] is True
        assert item["start"] == DAY.isoformat()
        assert "😴" in item["title"]
        assert "✗" in item["title"]  # 450 < 480，未达标
        assert item["extendedProps"]["deviation_minutes"] == -30

    def test_on_target_record_is_green_with_check(self, db, him):
        upsert_daily_record(db, him, DAY, actual_minutes=90, today=DAY)
        item = next(
            i for i in build_feed(db, DAY, DAY)
            if i["extendedProps"]["kind"] == "record"
        )
        assert "✓" in item["title"]
        assert item["color"] == "#10b981"

    def test_all_day_event(self, db, her):
        create_event(db, her, title="出游", event_date=DAY)
        item = next(
            i for i in build_feed(db, DAY, DAY)
            if i["extendedProps"]["kind"] == "event"
        )
        assert item["allDay"] is True
        assert item["start"] == DAY.isoformat()
        assert "end" not in item

    def test_timed_event_carries_start_and_end(self, db, her):
        create_event(
            db, her, title="看电影", event_date=DAY,
            start_time=time(20, 0), end_time=time(22, 30),
        )
        item = next(
            i for i in build_feed(db, DAY, DAY)
            if i["extendedProps"]["kind"] == "event"
        )
        assert item["allDay"] is False
        assert item["start"] == "2026-10-09T20:00:00"
        assert item["end"] == "2026-10-09T22:30:00"

    def test_range_filter_applies(self, db, her):
        upsert_daily_record(db, her, date(2026, 9, 1), actual_minutes=480, today=DAY)
        upsert_daily_record(db, her, DAY, actual_minutes=480, today=DAY)

        feed = build_feed(db, DAY, DAY)
        assert len(feed) == 1

    def test_ids_are_namespaced(self, db, her):
        """记录和事件的 id 不能撞——FullCalendar 用 id 去重。"""
        upsert_daily_record(db, her, DAY, actual_minutes=480, today=DAY)
        create_event(db, her, title="x", event_date=DAY)

        ids = [i["id"] for i in build_feed(db, DAY, DAY)]
        assert len(set(ids)) == len(ids)
        assert any(i.startswith("record-") for i in ids)
        assert any(i.startswith("event-") for i in ids)


class TestStats:
    def test_date_range_is_inclusive_and_ends_today(self):
        axis = date_range(DAY, 7)
        assert len(axis) == 7
        assert axis[-1] == DAY
        assert axis[0] == date(2026, 10, 3)

    def test_missing_days_are_null_not_zero(self, db, her, him):
        """补 0 会让图看起来像「那天偏差正好为 0」，是在骗人。"""
        upsert_daily_record(db, her, DAY, actual_minutes=450, today=DAY)
        stats = build_stats(db, DAY, days=7)

        person = next(p for p in stats["people"] if p["role"] == "female")
        assert person["deviation"][-1] == -30
        assert person["deviation"][0] is None

    def test_cumulative_holds_flat_across_gaps(self, db, her, him):
        upsert_daily_record(db, her, date(2026, 10, 7), actual_minutes=510, today=DAY)
        upsert_daily_record(db, her, DAY, actual_minutes=450, today=DAY)

        person = next(
            p for p in build_stats(db, DAY, days=5)["people"] if p["role"] == "female"
        )
        # 10/7 +30 → 10/8 没打卡保持 30 → 10/9 -30 回到 0
        assert person["cumulative"][-3:] == [30, 30, 0]

    def test_days_param_is_bounded(self, db, her, him):
        assert build_stats(db, DAY, days=1)["days"] == 7
        assert build_stats(db, DAY, days=9999)["days"] == 365

    def test_summary_included_per_person(self, db, her, him):
        upsert_daily_record(db, her, DAY, actual_minutes=480, today=DAY)
        person = next(
            p for p in build_stats(db, DAY, days=30)["people"] if p["role"] == "female"
        )
        assert person["summary"]["total_days"] == 1
        assert person["summary"]["on_target_days"] == 1
        assert person["summary"]["on_target_rate"] == 1.0


class TestPages:
    def _login(self, client):
        from tests.conftest import PASSWORD

        client.post("/login", data={"username": "her", "password": PASSWORD})

    def test_calendar_page_renders(self, client, her):
        self._login(client)
        response = client.get("/calendar")
        assert response.status_code == 200
        assert "FullCalendar" in response.text

    def test_calendar_feed_is_json(self, client, her, him, db):
        self._login(client)
        upsert_daily_record(db, her, DAY, actual_minutes=450, today=DAY)

        response = client.get(f"/api/calendar?start={DAY}&end={DAY}")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_feed_tolerates_iso_datetime_bounds(self, client, her):
        """FullCalendar 可能传带时区的完整时间戳，不能因此 500。"""
        self._login(client)
        response = client.get(
            "/api/calendar?start=2026-10-01T00:00:00%2B08:00&end=2026-10-31T00:00:00%2B08:00"
        )
        assert response.status_code == 200

    def test_feed_tolerates_garbage_bounds(self, client, her):
        self._login(client)
        assert client.get("/api/calendar?start=哈哈&end=").status_code == 200

    def test_stats_page_renders(self, client, her, him):
        self._login(client)
        response = client.get("/stats?days=30")
        assert response.status_code == 200
        assert "每日偏差" in response.text

    def test_anniversaries_page_renders(self, client, her):
        self._login(client)
        assert client.get("/anniversaries").status_code == 200

    def test_settings_page_renders_with_reminders(self, client, her):
        self._login(client)
        response = client.get("/settings")
        assert response.status_code == 200
        assert "推送渠道" in response.text
        assert "提醒规则" in response.text
