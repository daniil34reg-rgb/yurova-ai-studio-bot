from aiogram.types import User as TgUser

from bot.models import User, UserRole
from bot.repositories import UserRepository


class UserService:
    def __init__(self, repo: UserRepository):
        self.repo = repo

    async def register_or_update(self, tg_user: TgUser) -> tuple[User, bool]:
        return await self.repo.get_or_create(
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
        )

    async def get_profile(self, telegram_id: int) -> User | None:
        return await self.repo.get_by_telegram_id(telegram_id)

    async def ban(self, telegram_id: int) -> None:
        await self.repo.set_role(telegram_id, UserRole.banned)

    async def unban(self, telegram_id: int) -> None:
        await self.repo.set_role(telegram_id, UserRole.user)

    async def save_phone(self, telegram_id: int, phone_number: str) -> None:
        await self.repo.set_phone(telegram_id, phone_number)

    async def save_customer_full_name(self, telegram_id: int, full_name: str) -> None:
        await self.repo.set_customer_full_name(telegram_id, full_name)

    async def save_city(self, telegram_id: int, city: str) -> None:
        await self.repo.set_city(telegram_id, city)

    async def is_banned(self, telegram_id: int) -> bool:
        user = await self.repo.get_by_telegram_id(telegram_id)
        return user is not None and user.role == UserRole.banned
