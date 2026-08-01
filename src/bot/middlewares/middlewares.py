from typing import Callable, Awaitable, Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message
from cachetools import TTLCache

from bot.config import settings

# 3 requests per 3 seconds per user
flood_cache: TTLCache = TTLCache(maxsize=10_000, ttl=3)


class AntiFloodMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        uid = user.id
        hits = flood_cache.get(uid, 0)
        if hits >= 5:
            if isinstance(event, Message):
                await event.answer("⏳ Too many requests. Please wait a moment.")
            return None

        flood_cache[uid] = hits + 1
        return await handler(event, data)


class BanCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        # Admins bypass ban check
        if user.id in settings.admin_ids:
            return await handler(event, data)

        session = data.get("session")
        if session:
            from bot.repositories import UserRepository
            repo = UserRepository(session)
            db_user = await repo.get_by_telegram_id(user.id)
            if db_user and db_user.role.value == "banned":
                if isinstance(event, Message):
                    await event.answer("🚫 You are banned from using this bot.")
                return None

        return await handler(event, data)


class DatabaseMiddleware(BaseMiddleware):
    def __init__(self, session_maker):
        self.session_maker = session_maker

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_maker() as session:
            data["session"] = session
            return await handler(event, data)
