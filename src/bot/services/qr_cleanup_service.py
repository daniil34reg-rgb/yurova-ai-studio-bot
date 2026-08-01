import asyncio
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.logging_setup.logger import logger
from bot.repositories import SentQRMessageRepository, SettingsRepository

QR_AUTO_DELETE_HOURS_KEY = "qr_auto_delete_hours"
DEFAULT_QR_AUTO_DELETE_HOURS = 24
MAX_QR_AUTO_DELETE_HOURS = 47


def utc_now() -> datetime:
    # The database uses timezone-naive UTC timestamps on both SQLite and PostgreSQL.
    return datetime.now(UTC).replace(tzinfo=None)


async def get_qr_auto_delete_hours(session: AsyncSession) -> int:
    raw_value = await SettingsRepository(session).get(
        QR_AUTO_DELETE_HOURS_KEY,
        str(DEFAULT_QR_AUTO_DELETE_HOURS),
    )
    try:
        hours = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_QR_AUTO_DELETE_HOURS
    if hours == 0:
        return 0
    if 1 <= hours <= MAX_QR_AUTO_DELETE_HOURS:
        return hours
    return DEFAULT_QR_AUTO_DELETE_HOURS


async def schedule_qr_deletion(session: AsyncSession, chat_id: int, message_id: int) -> bool:
    hours = await get_qr_auto_delete_hours(session)
    if hours == 0:
        return False
    await SentQRMessageRepository(session).add(
        chat_id=chat_id,
        message_id=message_id,
        delete_after=utc_now() + timedelta(hours=hours),
    )
    return True


async def cleanup_due_qr_messages(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    limit: int = 100,
) -> tuple[int, int]:
    """Delete one page of expired QR messages and return (deleted, deferred)."""
    async with session_factory() as session:
        repository = SentQRMessageRepository(session)
        due_messages = await repository.list_due(utc_now(), limit=limit)
        completed_ids: list[int] = []
        deferred = 0

        for record in due_messages:
            try:
                await bot.delete_message(chat_id=record.chat_id, message_id=record.message_id)
            except (TelegramBadRequest, TelegramForbiddenError) as error:
                # The message can already be gone, the user can block the bot, or
                # Telegram can reject an old message. Retrying those forever cannot help.
                logger.info(
                    f"QR message {record.chat_id}/{record.message_id} no longer deletable: {error}"
                )
                completed_ids.append(record.id)
            except Exception as error:
                logger.warning(
                    f"Could not delete QR message {record.chat_id}/{record.message_id}; will retry: {error}"
                )
                deferred += 1
            else:
                completed_ids.append(record.id)

        await repository.delete_ids(completed_ids)
        return len(completed_ids), deferred


async def qr_cleanup_worker(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    interval_seconds: int = 60,
) -> None:
    logger.info("QR auto-delete worker started.")
    while True:
        try:
            deleted, deferred = await cleanup_due_qr_messages(bot, session_factory)
            if deleted or deferred:
                logger.info(f"QR cleanup: completed={deleted}, deferred={deferred}.")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.exception(f"QR auto-delete worker error: {error}")
        await asyncio.sleep(interval_seconds)
