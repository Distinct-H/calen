"""应用配置。全部来自环境变量，代码里不留任何密钥。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_PLACEHOLDER = "dev-only-change-me"


def normalize_database_url(url: str) -> str:
    """把托管平台给的连接串规整成 SQLAlchemy + psycopg3 能用的形式。

    托管平台注入的 DATABASE_URL 有两种历史写法都会出问题：
    - ``postgres://``    SQLAlchemy 2.x 不认这个 scheme，直接抛错
    - ``postgresql://``  会去找 psycopg2，而 psycopg2 对 Python 3.13 支持不好
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite:///./data/couple.db"
    session_secret: str = INSECURE_PLACEHOLDER
    cron_secret: str = INSECURE_PLACEHOLDER
    default_timezone: str = "Asia/Shanghai"
    debug: bool = False
    session_max_age: int = 60 * 60 * 24 * 30  # 30 天免登录

    # 会话 Cookie 是否加 Secure 标记。None = 跟随 debug（生产加，开发不加）。
    #
    # ⚠️ 必须能单独关掉：浏览器**拒绝在 http:// 上保存 Secure Cookie**，
    # 所以还没配 HTTPS、暂时用 http://IP 访问时，如果强行加 Secure，
    # 登录会静默失败——提交后跳回登录页，不报任何错，极难排查。
    # 配好证书之后改成 true。
    secure_cookies: bool | None = None

    @property
    def sqlalchemy_url(self) -> str:
        return normalize_database_url(self.database_url)

    @property
    def session_https_only(self) -> bool:
        if self.secure_cookies is not None:
            return self.secure_cookies
        return not self.debug

    @property
    def is_sqlite(self) -> bool:
        return self.sqlalchemy_url.startswith("sqlite")

    def assert_production_ready(self) -> None:
        """生产环境启动前的自检：宁可起不来，也不要带着默认密钥对外服务。"""
        if self.debug:
            return
        placeholders = [
            name
            for name, value in (
                ("SESSION_SECRET", self.session_secret),
                ("CRON_SECRET", self.cron_secret),
            )
            if not value or value == INSECURE_PLACEHOLDER
        ]
        if placeholders:
            raise RuntimeError(
                f"生产环境必须设置 {', '.join(placeholders)}。"
                '生成命令：python3 -c "import secrets; print(secrets.token_urlsafe(48))"'
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
