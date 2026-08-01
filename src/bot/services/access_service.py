from aiogram import Bot

from bot.config import settings
from bot.repositories import AccessRepository
from bot.logging_setup.logger import logger


class AccessService:
    def __init__(self, repo: AccessRepository, bot: Bot):
        self.repo = repo
        self.bot = bot

    async def grant_access(self, user_id: int, telegram_id: int) -> str:
        await self.repo.create(user_id=user_id, access_type="channel")

        invite_link = settings.access_invite_link
        if not invite_link and settings.access_channel_id:
            try:
                link = await self.bot.create_chat_invite_link(
                    chat_id=settings.access_channel_id,
                    member_limit=1,
                )
                invite_link = link.invite_link
            except Exception as e:
                logger.error(f"Failed to create invite link: {e}")
                invite_link = "Contact admin for access"

        return invite_link

    async def has_access(self, user_id: int) -> bool:
        return await self.repo.has_active_access(user_id)

    async def revoke_access(self, user_id: int) -> None:
        await self.repo.revoke(user_id)
