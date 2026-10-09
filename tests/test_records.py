"""打卡写入与达标值快照。

本文件是整个设计最重要的保护网：验证「改达标值不会篡改历史存档」。
"""

from datetime import date

from app.services.records import (
    apply_target_change,
    get_record,
    upsert_daily_record,
)

TODAY = date(2026, 3, 10)
YESTERDAY = date(2026, 3, 9)
LAST_WEEK = date(2026, 3, 3)


class TestSnapshot:
    def test_new_record_snapshots_current_target(self, db, her):
        record = upsert_daily_record(db, her, TODAY, actual_minutes=420, today=TODAY)
        assert record.target_minutes == 480  # her 的达标值
        assert record.deviation_minutes == -60

    def test_changing_target_rewrites_only_today(self, db, her):
        """★ 核心性质：历史存档不随设置变动。"""
        past = upsert_daily_record(db, her, LAST_WEEK, actual_minutes=420, today=TODAY)
        today = upsert_daily_record(db, her, TODAY, actual_minutes=420, today=TODAY)
        assert past.deviation_minutes == -60
        assert today.deviation_minutes == -60

        # 把达标值从 8 小时下调到 7 小时
        apply_target_change(db, her, 420, today=TODAY)

        db.refresh(past)
        db.refresh(today)

        # 历史：一个字节都不许动
        assert past.target_minutes == 480
        assert past.deviation_minutes == -60

        # 今天：跟着重算，7 小时目标下 420 分钟刚好达标
        assert today.target_minutes == 420
        assert today.deviation_minutes == 0

    def test_editing_history_keeps_its_original_target(self, db, her):
        """补记/修正历史记录时，用的仍是当时的目标，不是现在的设置。"""
        upsert_daily_record(db, her, LAST_WEEK, actual_minutes=420, today=TODAY)
        apply_target_change(db, her, 600, today=TODAY)  # 目标改成 10 小时

        edited = upsert_daily_record(db, her, LAST_WEEK, actual_minutes=450, today=TODAY)

        assert edited.target_minutes == 480  # 仍是当时的 8 小时
        assert edited.deviation_minutes == -30

    def test_editing_today_resnapshots_target(self, db, her):
        """今天的记录是「活的」：刚调完目标就该在今天生效。"""
        upsert_daily_record(db, her, TODAY, actual_minutes=420, today=TODAY)
        her.target_minutes = 400
        db.commit()

        edited = upsert_daily_record(db, her, TODAY, actual_minutes=420, today=TODAY)

        assert edited.target_minutes == 400
        assert edited.deviation_minutes == 20

    def test_target_change_without_todays_record_is_safe(self, db, her):
        """今天还没打卡时改目标不应该报错，也不该凭空造出记录。"""
        apply_target_change(db, her, 420, today=TODAY)
        assert her.target_minutes == 420
        assert get_record(db, her.id, TODAY) is None


class TestUpsert:
    def test_second_submit_updates_instead_of_duplicating(self, db, her):
        first = upsert_daily_record(db, her, TODAY, actual_minutes=420, today=TODAY)
        second = upsert_daily_record(db, her, TODAY, actual_minutes=480, today=TODAY)

        assert first.id == second.id
        assert second.actual_minutes == 480
        assert second.deviation_minutes == 0

    def test_out_of_range_input_is_clamped(self, db, her):
        record = upsert_daily_record(db, her, TODAY, actual_minutes=99999, today=TODAY)
        assert record.actual_minutes == 24 * 60

    def test_blank_note_stored_as_null(self, db, her):
        record = upsert_daily_record(
            db, her, TODAY, actual_minutes=420, today=TODAY, note="   "
        )
        assert record.note is None

    def test_two_people_same_day_do_not_collide(self, db, her, him):
        hers = upsert_daily_record(db, her, TODAY, actual_minutes=420, today=TODAY)
        his = upsert_daily_record(db, him, TODAY, actual_minutes=90, today=TODAY)

        assert hers.id != his.id
        assert hers.deviation_minutes == -60  # 420 - 480
        assert his.deviation_minutes == 30  # 90 - 60


class TestApi:
    def _login(self, client, username):
        from tests.conftest import PASSWORD

        return client.post(
            "/login", data={"username": username, "password": PASSWORD}
        )

    def test_future_date_is_rejected(self, client, her):
        self._login(client, "her")
        response = client.post(
            "/records",
            data={"hours": 8, "minutes": 0, "record_date": "2099-01-01"},
        )
        assert response.status_code == 400

    def test_submit_then_read_back_via_api(self, client, her, him):
        self._login(client, "her")

        posted = client.post("/records", data={"hours": 7, "minutes": 30})
        assert posted.status_code == 200
        assert "已保存" in posted.text

        listing = client.get("/api/records").json()
        her_block = next(p for p in listing["people"] if p["role"] == "female")
        assert her_block["records"][0]["actual_minutes"] == 450
        assert her_block["records"][0]["target_minutes"] == 480
        assert her_block["records"][0]["deviation_minutes"] == -30
        assert her_block["records"][0]["on_target"] is False

    def test_yesterday_backfill_is_allowed(self, client, her):
        self._login(client, "her")
        response = client.post(
            "/records",
            data={"hours": 8, "minutes": 0, "record_date": YESTERDAY.isoformat()},
        )
        assert response.status_code == 200
