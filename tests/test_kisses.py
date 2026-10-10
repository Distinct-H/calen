"""亲亲兑换与每日结算。

核心保护网是 `test_changing_ratio_only_resettles_today` ——
比率是可改的，历史结算绝不能跟着变，否则「欠了多少」就再也对不上账。
"""

from datetime import date

import pytest

from app.models import KissSettlement
from app.services.kisses import (
    KISS_SCALE,
    MODE_CUSTOM,
    MODE_DEDUCT,
    apply_config_change,
    balance_centi,
    balance_series,
    convert,
    custom_balance_centi,
    get_config,
    get_settlement,
    minutes_to_centi,
    resettle_all,
    settle_day,
)
from app.services.records import apply_target_change, upsert_daily_record

TODAY = date(2026, 10, 10)
YESTERDAY = date(2026, 10, 9)
LAST_WEEK = date(2026, 10, 3)


def fill(db, user, minutes, day=TODAY, today=TODAY):
    return upsert_daily_record(db, user, day, actual_minutes=minutes, today=today)


class TestMinutesToCenti:
    def test_exact_ratio(self):
        # 45 分钟，3 分钟换 1 个 → 15 个 → 1500 centi
        assert minutes_to_centi(45, 3) == 15 * KISS_SCALE

    def test_fractional_is_kept_as_centi(self):
        # 10 分钟，3 分钟换 1 个 → 3.33 个
        assert minutes_to_centi(10, 3) == 333

    def test_zero_minutes(self):
        assert minutes_to_centi(0, 3) == 0

    def test_illegal_ratio_returns_zero_instead_of_crashing(self):
        assert minutes_to_centi(45, 0) == 0


class TestConvert:
    def test_male_lead_increases_debt(self):
        """pair_diff 为负 = 男生领先 → 女生欠的增加。"""
        result = convert(-60, minutes_per_kiss=3, female_lead_mode=MODE_DEDUCT, minutes_per_custom_unit=3)
        assert result.kiss_delta_centi == 20 * KISS_SCALE
        assert result.custom_delta_centi == 0

    def test_female_lead_deduct_reduces_debt(self):
        result = convert(30, minutes_per_kiss=3, female_lead_mode=MODE_DEDUCT, minutes_per_custom_unit=3)
        assert result.kiss_delta_centi == -10 * KISS_SCALE
        assert result.custom_delta_centi == 0

    def test_female_lead_custom_leaves_kisses_alone(self):
        result = convert(30, minutes_per_kiss=3, female_lead_mode=MODE_CUSTOM, minutes_per_custom_unit=5)
        assert result.kiss_delta_centi == 0
        assert result.custom_delta_centi == 6 * KISS_SCALE

    def test_tie_changes_nothing(self):
        result = convert(0, minutes_per_kiss=3, female_lead_mode=MODE_DEDUCT, minutes_per_custom_unit=3)
        assert result.kiss_delta_centi == 0
        assert result.custom_delta_centi == 0

    @pytest.mark.parametrize("ratio,expected_kisses", [(1, 60), (3, 20), (6, 10), (60, 1)])
    def test_ratio_scales_the_result(self, ratio, expected_kisses):
        result = convert(-60, ratio, MODE_DEDUCT, 3)
        assert result.kiss_delta_centi == expected_kisses * KISS_SCALE


class TestSettleDay:
    def test_needs_both_sides(self, db, her, him):
        fill(db, her, 450)  # 只有女生填了
        assert get_settlement(db, TODAY) is None

        fill(db, him, 90)  # 男生也填了，自动结算
        assert get_settlement(db, TODAY) is not None

    def test_settlement_snapshots_the_inputs(self, db, her, him):
        fill(db, her, 450)  # 450 - 480 = -30
        fill(db, him, 90)  # 90 - 60 = +30

        settlement = get_settlement(db, TODAY)
        assert settlement.female_deviation_minutes == -30
        assert settlement.male_deviation_minutes == 30
        assert settlement.pair_diff_minutes == -60  # 男生领先 60 分钟
        assert settlement.minutes_per_kiss == 3  # 默认比率
        # 60 分钟 ÷ 3 = 20 个亲亲
        assert settlement.kiss_delta_centi == 20 * KISS_SCALE

    def test_editing_a_record_resettles_that_day(self, db, her, him):
        fill(db, her, 450)
        fill(db, him, 90)
        assert balance_centi(db) == 20 * KISS_SCALE

        fill(db, her, 480)  # 女生改成刚好达标 → pair_diff = -30
        assert balance_centi(db) == 10 * KISS_SCALE

    def test_target_change_resettles_today(self, db, her, him):
        """改达标值会改变偏差 → 亲亲结算必须跟着重算。"""
        fill(db, her, 450)
        fill(db, him, 90)
        assert balance_centi(db) == 20 * KISS_SCALE

        apply_target_change(db, her, 450, today=TODAY)  # 女生目标降到 450，变成刚好达标
        # pair_diff = 0 - 30 = -30 → 10 个
        assert balance_centi(db) == 10 * KISS_SCALE

    def test_no_settlement_without_a_partner(self, db, her):
        fill(db, her, 450)
        assert get_settlement(db, TODAY) is None


class TestBalance:
    def test_sums_across_days(self, db, her, him):
        for day in (LAST_WEEK, YESTERDAY, TODAY):
            fill(db, her, 450, day=day)  # -30
            fill(db, him, 90, day=day)  # +30
        # 每天 20 个，三天 60 个
        assert balance_centi(db) == 60 * KISS_SCALE

    def test_female_lead_can_flip_the_debt(self, db, her, him):
        fill(db, her, 600, day=YESTERDAY)  # +120
        fill(db, him, 30, day=YESTERDAY)  # -30
        # pair_diff = +150 → 女生领先 → 抵扣 50 个
        assert balance_centi(db) == -50 * KISS_SCALE

    def test_custom_mode_accumulates_separately(self, db, her, him):
        apply_config_change(
            db, TODAY, minutes_per_kiss=3,
            female_lead_mode=MODE_CUSTOM,
            custom_reward_name="小红花", minutes_per_custom_unit=5,
        )
        fill(db, her, 600)  # +120
        fill(db, him, 30)  # -30  → pair_diff = +150，女生领先

        assert balance_centi(db) == 0  # 亲亲没动
        assert custom_balance_centi(db) == 30 * KISS_SCALE  # 150 ÷ 5 = 30 朵

    def test_series_carries_history_before_the_axis(self, db, her, him):
        fill(db, her, 450, day=LAST_WEEK)
        fill(db, him, 90, day=LAST_WEEK)  # 轴之前的 20 个
        fill(db, her, 450, day=TODAY)
        fill(db, him, 90, day=TODAY)  # 轴内再 20 个

        series = balance_series(db, [YESTERDAY, TODAY])
        assert series == [20 * KISS_SCALE, 40 * KISS_SCALE]


class TestRatioSnapshot:
    def test_changing_ratio_only_resettles_today(self, db, her, him):
        """★ 核心性质：历史结算保留当时的比率。"""
        for day in (LAST_WEEK, TODAY):
            fill(db, her, 450, day=day)
            fill(db, him, 90, day=day)

        past = get_settlement(db, LAST_WEEK)
        assert past.minutes_per_kiss == 3
        assert past.kiss_delta_centi == 20 * KISS_SCALE

        # 比率从 3:1 改成 6:1
        apply_config_change(
            db, TODAY, minutes_per_kiss=6,
            female_lead_mode=MODE_DEDUCT,
            custom_reward_name="小红花", minutes_per_custom_unit=3,
        )

        db.refresh(past)
        # 历史：一个字节都不许动
        assert past.minutes_per_kiss == 3
        assert past.kiss_delta_centi == 20 * KISS_SCALE

        # 今天：按新比率重算，60 ÷ 6 = 10 个
        today_row = get_settlement(db, TODAY)
        assert today_row.minutes_per_kiss == 6
        assert today_row.kiss_delta_centi == 10 * KISS_SCALE

        assert balance_centi(db) == 30 * KISS_SCALE  # 20 + 10

    def test_editing_history_keeps_its_original_ratio(self, db, her, him):
        fill(db, her, 450, day=LAST_WEEK)
        fill(db, him, 90, day=LAST_WEEK)
        apply_config_change(
            db, TODAY, minutes_per_kiss=10,
            female_lead_mode=MODE_DEDUCT,
            custom_reward_name="小红花", minutes_per_custom_unit=3,
        )

        # 回去改历史打卡：pair_diff 变了，但比率仍用当时的 3
        fill(db, him, 120, day=LAST_WEEK, today=TODAY)  # +60 → pair_diff = -90

        past = get_settlement(db, LAST_WEEK)
        assert past.minutes_per_kiss == 3
        assert past.kiss_delta_centi == 30 * KISS_SCALE  # 90 ÷ 3

    def test_ratio_is_clamped(self, db, her, him):
        config = apply_config_change(
            db, TODAY, minutes_per_kiss=99999,
            female_lead_mode=MODE_DEDUCT,
            custom_reward_name="x", minutes_per_custom_unit=0,
        )
        assert config.minutes_per_kiss == 600
        assert config.minutes_per_custom_unit == 1

    def test_unknown_mode_falls_back_to_deduct(self, db, her, him):
        config = apply_config_change(
            db, TODAY, minutes_per_kiss=3,
            female_lead_mode="瞎填的",
            custom_reward_name="x", minutes_per_custom_unit=3,
        )
        assert config.female_lead_mode == MODE_DEDUCT


class TestResettle:
    def test_backfills_unsettled_days(self, db, her, him):
        # 直接造打卡但绕过自动结算，模拟「功能上线前就有的历史数据」
        fill(db, her, 450, day=LAST_WEEK)
        fill(db, him, 90, day=LAST_WEEK)
        db.query(KissSettlement).delete()
        db.commit()
        assert balance_centi(db) == 0

        assert resettle_all(db, TODAY) == 1
        assert balance_centi(db) == 20 * KISS_SCALE


class TestConfigDefaults:
    def test_created_on_first_access(self, db):
        config = get_config(db)
        assert config.id == 1
        assert config.minutes_per_kiss == 3
        assert config.female_lead_mode == MODE_DEDUCT

    def test_second_access_reuses_the_row(self, db):
        get_config(db)
        get_config(db)
        assert db.query(type(get_config(db))).count() == 1


class TestLedgerOnPages:
    def _login(self, client):
        from tests.conftest import PASSWORD

        client.post("/login", data={"username": "her", "password": PASSWORD})

    def test_today_page_shows_the_debt(self, client, db, her, him):
        self._login(client)
        fill(db, her, 450)
        fill(db, him, 90)

        body = client.get("/").text
        assert "亲亲账本" in body
        assert "个亲亲" in body
        assert "小美 欠 小强" in body

    def test_today_page_when_settled(self, client, db, her, him):
        self._login(client)
        body = client.get("/").text
        assert "两清" in body

    def test_pending_when_partner_has_not_filled(self, client, db, her, him):
        self._login(client)
        fill(db, her, 450)
        assert "今天还没结算" in client.get("/").text

    def test_settings_shows_ratio_form(self, client, her, him):
        self._login(client)
        body = client.get("/settings").text
        assert "亲亲兑换规则" in body
        assert "分钟 : 1 个亲亲" in body

    def test_save_ratio_via_form(self, client, her, him):
        self._login(client)
        response = client.post(
            "/settings/kisses",
            data={"minutes_per_kiss": 5, "female_lead_mode": MODE_DEDUCT,
                  "custom_reward_name": "小红花", "minutes_per_custom_unit": 4},
        )
        assert response.status_code == 200
        assert "历史结算保留原比率不变" in response.text

    def test_stats_page_shows_ledger(self, client, db, her, him):
        self._login(client)
        fill(db, her, 450)
        fill(db, him, 90)
        assert "亲亲账本" in client.get("/stats").text
