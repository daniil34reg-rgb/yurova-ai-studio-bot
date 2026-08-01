from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import settings
from bot.models import Base

if settings.database_url.startswith("sqlite"):
    Path("data").mkdir(parents=True, exist_ok=True)

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        columns = await conn.run_sync(
            lambda sync_conn: [col["name"] for col in inspect(sync_conn).get_columns("users")]
        )
        if "phone_number" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN phone_number VARCHAR(32)"))
        if "customer_full_name" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN customer_full_name VARCHAR(160)"))
        if "city" not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN city VARCHAR(128)"))

        sticker_button_columns = await conn.run_sync(
            lambda sync_conn: [col["name"] for col in inspect(sync_conn).get_columns("sticker_buttons")]
        )
        if "row_width" not in sticker_button_columns:
            await conn.execute(text("ALTER TABLE sticker_buttons ADD COLUMN row_width INTEGER NOT NULL DEFAULT 1"))
        if "issued_count" not in sticker_button_columns:
            await conn.execute(text("ALTER TABLE sticker_buttons ADD COLUMN issued_count INTEGER"))

        saved_sticker_button_columns = await conn.run_sync(
            lambda sync_conn: [col["name"] for col in inspect(sync_conn).get_columns("saved_sticker_buttons")]
        )
        if "row_width" not in saved_sticker_button_columns:
            await conn.execute(text("ALTER TABLE saved_sticker_buttons ADD COLUMN row_width INTEGER NOT NULL DEFAULT 1"))

        payment_method_columns = await conn.run_sync(
            lambda sync_conn: [col["name"] for col in inspect(sync_conn).get_columns("promotion_qr_codes")]
        )
        if "method_type" not in payment_method_columns:
            await conn.execute(
                text("ALTER TABLE promotion_qr_codes ADD COLUMN method_type VARCHAR(16) NOT NULL DEFAULT 'qr'")
            )
        if "payment_url" not in payment_method_columns:
            await conn.execute(
                text("ALTER TABLE promotion_qr_codes ADD COLUMN payment_url VARCHAR(1024)")
            )
        # Existing installations created file_id as NOT NULL.
        if settings.database_url.startswith("postgresql"):
            await conn.execute(
                text("ALTER TABLE promotion_qr_codes ALTER COLUMN file_id DROP NOT NULL")
            )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
