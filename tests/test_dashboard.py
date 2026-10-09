"""首页面板的视图模型。"""

from datetime import date

from app.services.dashboard import build_dashboard
from app.services.records import upsert_daily_record

DAY = date(2026, 3, 10)


def _fill(db, user, minutes):
    return upsert_daily_record(db, user, DAY, actual_minutes=minutes, today=DAY)


class TestPairDiff:
    def test_direction_is_stable_across_viewers(self, db, her, him):
        """「女生 − 男生」的定向不能随谁在登录而翻转，否则两人看到的结论会相反。"""
        _fill(db, her, 450)  # 450 - 480 = -30
        _fill(db, him, 90)  # 90 - 60 = +30

        seen_by_her = build_dashboard(db, her, DAY)
        seen_by_him = build_dashboard(db, him, DAY)

        assert seen_by_her.pair_diff == -60
        assert seen_by_him.pair_diff == -60
        assert seen_by_her.more_on_target.username == "him"
        assert seen_by_him.more_on_target.username == "him"

    def test_female_ahead(self, db, her, him):
        _fill(db, her, 540)  # +60
        _fill(db, him, 30)  # -30
        view = build_dashboard(db, her, DAY)
        assert view.pair_diff == 90
        assert view.more_on_target.username == "her"

    def test_none_when_partner_has_not_filled(self, db, her, him):
        _fill(db, her, 480)
        view = build_dashboard(db, her, DAY)
        assert view.pair_diff is None
        assert view.more_on_target is None

    def test_tie_has_no_winner(self, db, her, him):
        _fill(db, her, 480)  # 0
        _fill(db, him, 60)  # 0
        view = build_dashboard(db, her, DAY)
        assert view.pair_diff == 0
        assert view.more_on_target is None


class TestPersonView:
    def test_unfilled_day(self, db, her, him):
        view = build_dashboard(db, her, DAY)
        assert view.me.filled is False
        assert view.me.deviation is None
        assert view.me.actual_hm == (0, 0)

    def test_filled_day_exposes_form_values(self, db, her, him):
        _fill(db, her, 450)
        view = build_dashboard(db, her, DAY)
        assert view.me.filled is True
        assert view.me.actual_hm == (7, 30)
        assert view.me.target_hm == (8, 0)
        assert view.me.deviation == -30

    def test_partner_is_the_other_account(self, db, her, him):
        assert build_dashboard(db, her, DAY).partner.user.username == "him"
        assert build_dashboard(db, him, DAY).partner.user.username == "her"

    def test_solo_account_has_no_partner(self, db, her):
        view = build_dashboard(db, her, DAY)
        assert view.partner is None
        assert view.pair_diff is None
