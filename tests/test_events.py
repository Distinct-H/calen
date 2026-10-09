"""事件的增删改与校验。"""

from datetime import date, time

import pytest

from app.services.events import (
    EventValidationError,
    create_event,
    delete_event,
    format_time_range,
    list_events,
    parse_optional_time,
    update_event,
)

DAY = date(2026, 10, 9)


class TestParseOptionalTime:
    def test_blank_means_all_day(self):
        assert parse_optional_time("") is None
        assert parse_optional_time("   ") is None
        assert parse_optional_time(None) is None

    def test_valid_time(self):
        assert parse_optional_time("14:30") == time(14, 30)

    def test_invalid_raises(self):
        with pytest.raises(EventValidationError):
            parse_optional_time("25:99")


class TestValidation:
    def test_blank_title_rejected(self, db, her):
        with pytest.raises(EventValidationError, match="标题"):
            create_event(db, her, title="   ", event_date=DAY)

    def test_end_before_start_rejected(self, db, her):
        with pytest.raises(EventValidationError, match="结束时间"):
            create_event(
                db, her, title="看电影", event_date=DAY,
                start_time=time(20, 0), end_time=time(19, 0),
            )

    def test_end_without_start_rejected(self, db, her):
        with pytest.raises(EventValidationError, match="开始时间"):
            create_event(db, her, title="看电影", event_date=DAY, end_time=time(19, 0))

    def test_unknown_color_falls_back(self, db, her):
        event = create_event(db, her, title="随便", event_date=DAY, color="不存在的颜色")
        assert event.color == "slate"


class TestCrud:
    def test_create_all_day_event(self, db, her):
        event = create_event(db, her, title="纪念日出游", event_date=DAY)
        assert event.start_time is None
        assert event.is_shared is True
        assert event.created_by == her.id

    def test_blank_description_stored_as_null(self, db, her):
        event = create_event(db, her, title="x", event_date=DAY, description="  ")
        assert event.description is None

    def test_partner_can_edit_others_event(self, db, her, him):
        """这是共享日历，不是各自的私有日程。"""
        event = create_event(db, her, title="她建的", event_date=DAY)
        updated = update_event(db, event, title="他改的", event_date=DAY)
        assert updated.title == "他改的"
        assert updated.created_by == her.id  # 创建者不变

    def test_delete(self, db, her):
        event = create_event(db, her, title="删我", event_date=DAY)
        delete_event(db, event)
        assert list_events(db) == []

    def test_list_filters_by_range(self, db, her):
        create_event(db, her, title="九月", event_date=date(2026, 9, 1))
        create_event(db, her, title="十月", event_date=date(2026, 10, 15))

        in_october = list_events(db, start=date(2026, 10, 1), end=date(2026, 10, 31))
        assert [e.title for e in in_october] == ["十月"]


class TestFormatTimeRange:
    def test_all_day(self, db, her):
        event = create_event(db, her, title="x", event_date=DAY)
        assert format_time_range(event) == "全天"

    def test_start_only(self, db, her):
        event = create_event(db, her, title="x", event_date=DAY, start_time=time(14, 0))
        assert format_time_range(event) == "14:00 起"

    def test_full_range(self, db, her):
        event = create_event(
            db, her, title="x", event_date=DAY,
            start_time=time(14, 0), end_time=time(15, 30),
        )
        assert format_time_range(event) == "14:00 – 15:30"


class TestRoutes:
    def _login(self, client):
        from tests.conftest import PASSWORD

        client.post("/login", data={"username": "her", "password": PASSWORD})

    def test_create_via_form(self, client, her):
        self._login(client)
        response = client.post(
            "/events",
            data={"title": "看电影", "event_date": DAY.isoformat(),
                  "start_time": "20:00", "end_time": "22:00", "color": "rose"},
        )
        assert response.status_code == 200
        assert "事件已添加" in response.text
        assert "看电影" in response.text

    def test_validation_error_surfaces_to_user(self, client, her):
        self._login(client)
        response = client.post(
            "/events",
            data={"title": "倒了", "event_date": DAY.isoformat(),
                  "start_time": "22:00", "end_time": "20:00"},
        )
        assert "结束时间不能早于开始时间" in response.text

    def test_delete_twice_is_harmless(self, client, her, db):
        self._login(client)
        event = create_event(db, her, title="删我", event_date=DAY)

        assert client.post(f"/events/{event.id}/delete").status_code == 200
        assert client.post(f"/events/{event.id}/delete").status_code == 200

    def test_edit_missing_event_redirects_with_message(self, client, her):
        self._login(client)
        response = client.get("/events?edit=99999")
        assert "已经不存在" in response.text
