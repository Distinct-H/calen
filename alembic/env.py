"""Alembic 环境。

连接串统一从 app.config 读，这样本地（SQLite）和生产（Postgres）
用同一套迁移，不需要在 alembic.ini 里重复配置。
"""

from logging.config import fileConfig

from alembic import context

from app.config import settings
from app.db import engine
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# SQLite 不支持大多数 ALTER TABLE，batch 模式会自动改写成
# 建新表→拷数据→换名。本地开发不加这个，改字段的迁移全会失败。
COMMON_OPTS = {
    "target_metadata": target_metadata,
    "render_as_batch": True,
    "compare_type": True,
}


def run_migrations_offline() -> None:
    context.configure(
        url=settings.sqlalchemy_url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **COMMON_OPTS,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(connection=connection, **COMMON_OPTS)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
