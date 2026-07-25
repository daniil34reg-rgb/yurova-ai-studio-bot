from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from portrait_bot.config import Settings
from portrait_bot.models import Base


class Database:
    def __init__(self, settings: Settings) -> None:
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_all(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(self._ensure_compatible_schema)

    @staticmethod
    def _ensure_compatible_schema(connection: Connection) -> None:
        ledger_columns = {
            item["name"] for item in inspect(connection).get_columns("ledger_entries")
        }
        if "expires_at" not in ledger_columns:
            connection.execute(text("ALTER TABLE ledger_entries ADD COLUMN expires_at TIMESTAMP"))
        template_columns = {item["name"] for item in inspect(connection).get_columns("templates")}
        if "preview_path" not in template_columns:
            connection.execute(text("ALTER TABLE templates ADD COLUMN preview_path TEXT"))
        if "sort_order" not in template_columns:
            connection.execute(
                text("ALTER TABLE templates ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 100")
            )
        package_columns = {item["name"] for item in inspect(connection).get_columns("packages")}
        if "sort_order" not in package_columns:
            connection.execute(
                text("ALTER TABLE packages ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 100")
            )

    async def drop_all(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()
