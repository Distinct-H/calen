"""认证与访问控制。"""

import pytest

from app.auth import authenticate, hash_password, verify_password
from app.config import Settings
from tests.conftest import PASSWORD


class TestSecureCookieSwitch:
    """会话 Cookie 的 Secure 标记必须能单独开关。

    浏览器**拒绝在 http:// 上保存 Secure Cookie**。所以在还没配 HTTPS、
    暂时用 http://服务器IP 访问的阶段，如果强行加 Secure，登录会静默失败——
    提交后跳回登录页，不报任何错误，极难排查。
    """

    @pytest.mark.parametrize(
        "debug,override,expected",
        [
            (False, None, True),    # 生产默认加 Secure
            (False, False, False),  # 还没配 HTTPS 时必须能关掉
            (False, True, True),    # 配好证书后显式打开
            (True, None, False),    # 本地开发走 http，不能加
            (True, True, True),     # 本地也允许强制打开
        ],
    )
    def test_resolves_from_debug_and_override(self, debug, override, expected):
        settings = Settings(
            debug=debug,
            secure_cookies=override,
            session_secret="s" * 40,
            cron_secret="c" * 40,
        )
        assert settings.session_https_only is expected


class TestPasswordHashing:
    def test_roundtrip(self):
        digest = hash_password(PASSWORD)
        assert digest != PASSWORD  # 不是明文存的
        assert verify_password(PASSWORD, digest)

    def test_wrong_password_fails(self):
        assert not verify_password("nope", hash_password(PASSWORD))

    def test_salted_hashes_differ(self):
        assert hash_password(PASSWORD) != hash_password(PASSWORD)

    def test_garbage_hash_does_not_raise(self):
        """数据库里的哈希被损坏时应返回 False，而不是抛异常 500。"""
        assert not verify_password(PASSWORD, "not-a-valid-argon2-hash")


class TestAuthenticate:
    def test_success(self, db, her):
        assert authenticate(db, "her", PASSWORD) is not None

    def test_wrong_password(self, db, her):
        assert authenticate(db, "her", "wrong") is None

    def test_unknown_user(self, db, her):
        assert authenticate(db, "nobody", PASSWORD) is None


class TestAccessControl:
    def test_anonymous_page_redirects_to_login(self, client):
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_anonymous_api_returns_401(self, client):
        response = client.get("/api/records")
        assert response.status_code == 401

    def test_htmx_request_gets_hx_redirect(self, client):
        """HTMX 不跟随 303，必须用 HX-Redirect 才能真的跳到登录页。"""
        response = client.post("/records", headers={"HX-Request": "true"})
        assert response.status_code == 401
        assert response.headers["HX-Redirect"] == "/login"

    def test_login_then_access(self, client, her):
        client.post("/login", data={"username": "her", "password": PASSWORD})
        response = client.get("/")
        assert response.status_code == 200
        assert "小美" in response.text

    def test_bad_login_shows_error_and_stays_out(self, client, her):
        response = client.post("/login", data={"username": "her", "password": "wrong"})
        assert response.status_code == 401
        assert "用户名或密码不正确" in response.text

        assert client.get("/", follow_redirects=False).status_code == 303

    def test_logout_clears_session(self, client, her):
        client.post("/login", data={"username": "her", "password": PASSWORD})
        assert client.get("/").status_code == 200

        client.post("/logout")
        assert client.get("/", follow_redirects=False).status_code == 303

    def test_healthz_is_public(self, client):
        assert client.get("/healthz").json() == {"status": "ok"}
