from __future__ import annotations

import asyncio
import logging

from aiogram.exceptions import TelegramNetworkError

from bot.database import async_session_maker as store_session_maker
from bot.database import create_tables as create_store_tables
from bot.services import qr_cleanup_worker
from portrait_bot.app_factory import create_context
from portrait_bot.bot import setup_commands
from portrait_bot.catalog import seed_catalog
from portrait_bot.config import get_settings
from portrait_bot.context import AppContext
from portrait_bot.runtime import cancel_task, worker_loop
from portrait_bot.storefront import seed_storefront_settings

logger = logging.getLogger(__name__)


async def initialize_telegram(context: AppContext, retry_seconds: float) -> None:
    if not context.bot:
        raise RuntimeError("Telegram initialization failed")
    while True:
        try:
            await context.bot.delete_webhook(drop_pending_updates=False)
            await setup_commands(context.bot, context)
            return
        except TelegramNetworkError as error:
            logger.warning(
                "Telegram is temporarily unavailable (%s). Retrying in %.1f seconds.",
                error,
                retry_seconds,
            )
            await asyncio.sleep(retry_seconds)


async def run() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for polling")
    context = create_context(settings)
    if not context.bot or not context.dispatcher:
        raise RuntimeError("Telegram initialization failed")
    worker_task: asyncio.Task[None] | None = None
    store_cleanup_task: asyncio.Task[None] | None = None
    try:
        await context.db.create_all()
        await create_store_tables()
        async with context.db.sessions() as session:
            await seed_catalog(
                session,
                settings.templates_file,
                settings.packages_file,
                settings.features_file,
            )
        await seed_storefront_settings(context)
        await initialize_telegram(context, settings.telegram_retry_seconds)
        worker_task = asyncio.create_task(worker_loop(context))
        store_cleanup_task = asyncio.create_task(
            qr_cleanup_worker(context.bot, store_session_maker)
        )
        await context.dispatcher.start_polling(context.bot, context=context)
    finally:
        if worker_task:
            await cancel_task(worker_task)
        if store_cleanup_task:
            await cancel_task(store_cleanup_task)
        await context.bot.session.close()
        await context.db.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
