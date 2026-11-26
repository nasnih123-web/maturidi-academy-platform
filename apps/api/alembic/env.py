"""Alembic env — نسخهٔ async (فاز ۰ §۱۲: فقط forward-only)."""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ثبت همهٔ مدل‌ها در metadata — بدون این import، autogenerate خالی می‌سازد
import app.models  # noqa: F401
from alembic import context
from app.core.config import get_settings
from app.core.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def include_object(object, name, type_, *args, **kwargs) -> bool | None:
    """فیلتر اشیای autogenerate — برای ایندکس‌های عمدیِ خارج‌از-مدل.

    HNSW و trgm روی fiqh_knowledge_chunks صرفاً ایندکس‌های عملکردی
    PostgreSQL هستند: مایگریشن e2b3c4d5f6a7 آن‌ها را فقط روی PG می‌سازد
    (gated با is_pg) و عمداً در مدل نیستند، چون Index سطح مدل به همهٔ
    دایالکت‌ها تسری می‌یابد (create_all و بازسازی‌های batch روی SQLite
    ایندکس btree ساده روی ستون بردار می‌ساختند — در حالی که طراحی
    مایگریشن آن‌ها را از اسکیما SQLite دور نگه داشته است).
    بازگشت None = بی‌نظر (رفتار پیش‌فرض alembic برای بقیهٔ اشیاء).
    """
    if type_ == "index" and name in (
        "ix_fiqh_chunks_embedding_vec_hnsw",
        "ix_fiqh_chunks_text_trgm",
    ):
        return False
    return None


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
