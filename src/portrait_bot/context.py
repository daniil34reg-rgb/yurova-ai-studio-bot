from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot, Dispatcher

from portrait_bot.config import Settings
from portrait_bot.db import Database
from portrait_bot.providers.images import ImageProvider
from portrait_bot.providers.payments import PaymentProvider
from portrait_bot.providers.videos import VideoProvider
from portrait_bot.services import GenerationWorker


@dataclass(slots=True)
class AppContext:
    settings: Settings
    db: Database
    image_provider: ImageProvider
    video_provider: VideoProvider
    payment_provider: PaymentProvider
    worker: GenerationWorker
    bot: Bot | None = None
    dispatcher: Dispatcher | None = None
