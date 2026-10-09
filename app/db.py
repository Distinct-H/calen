"""数据库引擎与会话。同步 SQLAlchemy —— 两个用户的量级，异步只会增加复杂度。"""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


def _ensure_sqlite_dir(url: str) -> None:
    """SQLite 不会自动创建父目录，首次启动会因为 data/ 不存在而失败。"""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return
    path = Path(url[len(prefix) :]).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(settings.sqlalchemy_url)

engine = create_engine(
    settings.sqlalchemy_url,
    # FastAPI 的同步端点跑在线程池里，SQLite 连接会跨线程使用
    connect_args={"check_same_thread": False} if settings.is_sqlite else {},
    # 托管 Postgres 会掐断空闲连接，不加这个会偶发 OperationalError
    pool_pre_ping=True,
    echo=False,
)

if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        """SQLite 默认不校验外键，必须逐连接打开。"""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
