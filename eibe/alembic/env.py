"""Alembic 실행 환경.

DB URL 은 app.config.settings 에서만 가져온다 (.env 단일 출처).
SQLite 와 PostgreSQL 양쪽에서 동일한 마이그레이션이 돌도록 구성한다.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings

# 모든 모델을 등록시키기 위한 import — autogenerate 가 테이블을 인식하려면 필요하다.
from app.models import Base  # noqa: F401
import app.models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata


def _common_options() -> dict[str, object]:
    return {
        "target_metadata": target_metadata,
        # 컬럼 타입 변경을 감지한다 (Text → Date 같은 변경을 놓치지 않도록).
        "compare_type": True,
        "compare_server_default": True,
        # SQLite 는 ALTER TABLE 지원이 빈약해 임시 테이블로 우회해야 한다.
        # PostgreSQL 에서는 불필요하지만 켜져 있어도 무해하다.
        "render_as_batch": settings.is_sqlite,
    }


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_common_options(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, **_common_options())
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
