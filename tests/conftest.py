"""测试公共夹具。

环境变量必须在导入 app 之前设置好——app.config.settings 是模块级单例，
导入那一刻就定型了。pydantic-settings 的优先级是「环境变量 > .env 文件」，
所以这里设的值会盖掉项目根目录的 .env。
"""

import os
import tempfile

_TMPDIR = tempfile.mkdtemp(prefix="couple-cal-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMPDIR}/test.db"
os.environ["DEBUG"] = "true"
os.environ["SESSION_SECRET"] = "test-only-session-secret"
os.environ["CRON_SECRET"] = "test-only-cron-secret"
os.environ["DEFAULT_TIMEZONE"] = "Asia/Shanghai"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    METRIC_EXERCISE,
    METRIC_SLEEP,
    ROLE_FEMALE,
    ROLE_MALE,
    Base,
    User,
)

PASSWORD = "TestPassword123"


@pytest.fixture(autouse=True)
def fresh_schema():
    """每个用例一张干净的表。两人量级下建表开销可忽略。"""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    return TestClient(app)


def _make_user(db, username, display_name, role, metric, target) -> User:
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        display_name=display_name,
        role=role,
        metric_type=metric,
        target_minutes=target,
        timezone="Asia/Shanghai",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def her(db) -> User:
    """女生：记睡眠，达标 8 小时。"""
    return _make_user(db, "her", "小美", ROLE_FEMALE, METRIC_SLEEP, 480)


@pytest.fixture
def him(db) -> User:
    """男生：记锻炼，达标 1 小时。"""
    return _make_user(db, "him", "小强", ROLE_MALE, METRIC_EXERCISE, 60)
