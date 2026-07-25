from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from portrait_bot.bot import build_dispatcher
from portrait_bot.config import Settings
from portrait_bot.context import AppContext
from portrait_bot.db import Database
from portrait_bot.providers.images import build_image_provider
from portrait_bot.providers.payments import build_payment_provider
from portrait_bot.providers.videos import build_video_provider
from portrait_bot.services import GenerationWorker


def create_context(settings: Settings) -> AppContext:
    settings.prepare_directories()
    db = Database(settings)
    image_provider = build_image_provider(settings)
    video_provider = build_video_provider(settings)
    payment_provider = build_payment_provider(settings)
    worker = GenerationWorker(db.sessions, image_provider, settings, video_provider)
    context = AppContext(
        settings=settings,
        db=db,
        image_provider=image_provider,
        video_provider=video_provider,
        payment_provider=payment_provider,
        worker=worker,
    )
    if settings.telegram_bot_token:
        context.bot = Bot(
            token=settings.telegram_bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        context.dispatcher = build_dispatcher(context)
    return context
