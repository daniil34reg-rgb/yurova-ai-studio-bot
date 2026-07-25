from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path

from aiogram.types import FSInputFile, InputSticker
from sqlalchemy import select

from portrait_bot.context import AppContext
from portrait_bot.keyboards import post_generation_menu
from portrait_bot.models import (
    BotSetting,
    FeatureFlag,
    Generation,
    GenerationStatus,
    User,
)
from portrait_bot.money import format_rub
from portrait_bot.services import generation_reactions, result_paths
from portrait_bot.sticker_options import reaction_by_key

logger = logging.getLogger(__name__)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def cleanup_expired_files(context: AppContext) -> None:
    now = datetime.now(UTC)
    async with context.db.sessions() as session:
        generations = list((await session.scalars(select(Generation))).all())
    for generation in generations:
        reference = _aware(generation.completed_at or generation.created_at)
        source = Path(generation.source_path)
        if now - reference >= timedelta(hours=context.settings.source_retention_hours):
            await asyncio.to_thread(source.unlink, missing_ok=True)
        if now - reference >= timedelta(days=context.settings.result_retention_days):
            for path in result_paths(generation):
                await asyncio.to_thread(path.unlink, missing_ok=True)


def _sticker_set_name(telegram_id: int, generation_id: str, bot_username: str) -> str:
    username = re.sub(r"[^a-zA-Z0-9_]", "", bot_username).lower()
    suffix = f"_by_{username}"
    prefix = f"yurova_ai_{telegram_id}_{generation_id[:8]}"
    return (prefix[: 64 - len(suffix)] + suffix).strip("_")


async def _deliver_sticker_pack(
    context: AppContext,
    user: User,
    generation: Generation,
    paths: list[Path],
) -> None:
    if context.bot is None:
        return
    reaction_keys = generation_reactions(generation)
    me = await context.bot.get_me()
    bot_username = me.username or context.settings.service_bot_username
    set_name = _sticker_set_name(user.telegram_id, generation.id, bot_username)
    title = f"Yurova AI Studio • Набор {generation.id[:8]}"[:64]
    stickers = [
        InputSticker(
            sticker=FSInputFile(path),
            format="static",
            emoji_list=[
                "😂"
                if reaction_keys[index] == "meme"
                else reaction_by_key(reaction_keys[index]).emoji
            ],
        )
        for index, path in enumerate(paths)
    ]
    pack_created = False
    try:
        pack_created = await context.bot.create_new_sticker_set(
            user_id=user.telegram_id,
            name=set_name,
            title=title,
            stickers=stickers,
            sticker_format="static",
        )
    except Exception:
        logger.exception("Could not create Telegram sticker set for %s", generation.id)

    for path in paths:
        await context.bot.send_sticker(user.telegram_id, FSInputFile(path))

    text = (
        f"Готово! Создано стикеров: <b>{len(paths)}</b> ✨\nЗаказ: <code>{generation.id[:8]}</code>"
    )
    if pack_created:
        text += f'\n\n<a href="https://t.me/addstickers/{set_name}">Добавить стикерпак</a>'
    else:
        text += "\n\nСтикеры отправлены файлами. Сборку набора можно повторить через поддержку."
    async with context.db.sessions() as session:
        flags = list((await session.scalars(select(FeatureFlag))).all())
        message_setting = await session.get(BotSetting, "post_generation_message")
    features = {flag.key: flag.enabled for flag in flags}
    next_message = message_setting.value if message_setting else "Что хотите сделать дальше?"
    await context.bot.send_message(
        user.telegram_id,
        text + f"\n\n{next_message}",
        reply_markup=post_generation_menu(features),
    )


async def worker_loop(context: AppContext, *, idle_seconds: float = 1.0) -> None:
    last_cleanup = 0.0
    while True:
        current = asyncio.get_running_loop().time()
        if current - last_cleanup >= 3600:
            await cleanup_expired_files(context)
            last_cleanup = current
        generation = await context.worker.process_one()
        if generation is None:
            await asyncio.sleep(idle_seconds)
            continue
        if context.bot is None:
            continue
        async with context.db.sessions() as session:
            user = await session.scalar(select(User).where(User.id == generation.user_id))
        if not user:
            continue
        try:
            if generation.status == GenerationStatus.COMPLETED.value and generation.result_path:
                paths = [
                    path
                    for path in result_paths(generation)
                    if await asyncio.to_thread(path.exists)
                ]
                if generation.mode.startswith("sticker:") and paths:
                    await _deliver_sticker_pack(context, user, generation, paths)
                elif generation.mode.startswith("video:") and paths:
                    await context.bot.send_video(
                        user.telegram_id,
                        FSInputFile(paths[0]),
                        caption=(
                            "Фото ожило ✨\n"
                            f"Задание <code>{generation.id[:8]}</code>"
                        ),
                    )
                elif paths:
                    await context.bot.send_photo(
                        user.telegram_id,
                        FSInputFile(paths[0]),
                        caption=(f"Готово ✨\nЗаказ <code>{generation.id[:8]}</code>"),
                    )
                else:
                    raise FileNotFoundError("Generation result is missing")
            else:
                refund_note = (
                    " Списанная сумма автоматически возвращена "
                    f"на баланс ({format_rub(generation.price_rub)})."
                    if generation.price_rub > 0
                    else ""
                )
                if generation.mode.startswith("video:"):
                    details = ""
                    if user.telegram_id in context.settings.admin_ids:
                        error_code = escape(generation.error_code or "unknown_error")
                        error_message = escape(
                            (generation.error_message or "Причина не указана")[:800]
                        )
                        details = (
                            "\n\n<b>Техническая причина:</b>\n"
                            f"<code>{error_code}</code>\n{error_message}"
                        )
                    await context.bot.send_message(
                        user.telegram_id,
                        "Не удалось оживить фотографию. Попробуйте другое фото "
                        f"или повторите позже.{refund_note}\n"
                        f"Задание: <code>{generation.id[:8]}</code>"
                        f"{details}",
                    )
                    continue
                await context.bot.send_message(
                    user.telegram_id,
                    f"Не удалось обработать фотографию.{refund_note}\n"
                    f"Заказ: <code>{generation.id[:8]}</code>",
                )
        except Exception:
            # Delivery failures remain visible in application logs in production.
            continue


async def cancel_task(task: asyncio.Task[object] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
