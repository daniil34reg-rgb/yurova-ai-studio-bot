from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models import User, UserProfileChange, UserRole


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def create(self, telegram_id: int, username: str | None, full_name: str) -> User:
        user = User(telegram_id=telegram_id, username=username, full_name=full_name)
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_or_create(self, telegram_id: int, username: str | None, full_name: str) -> tuple[User, bool]:
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            # Update username / name if changed
            if user.username != username or user.full_name != full_name:
                user.username = username
                user.full_name = full_name
                await self.session.commit()
            return user, False
        user = await self.create(telegram_id, username, full_name)
        return user, True

    async def set_role(self, telegram_id: int, role: UserRole) -> None:
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            user.role = role
            await self.session.commit()

    async def set_phone(self, telegram_id: int, phone_number: str) -> None:
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            if user.phone_number and user.phone_number != phone_number:
                self.session.add(
                    UserProfileChange(
                        user_id=user.id,
                        field_name="phone_number",
                        old_value=user.phone_number,
                        new_value=phone_number,
                    )
                )
            user.phone_number = phone_number
            await self.session.commit()

    async def set_customer_full_name(self, telegram_id: int, full_name: str) -> None:
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            if user.customer_full_name and user.customer_full_name != full_name:
                self.session.add(
                    UserProfileChange(
                        user_id=user.id,
                        field_name="customer_full_name",
                        old_value=user.customer_full_name,
                        new_value=full_name,
                    )
                )
            user.customer_full_name = full_name
            await self.session.commit()

    async def set_city(self, telegram_id: int, city: str) -> None:
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            if user.city and user.city != city:
                self.session.add(
                    UserProfileChange(
                        user_id=user.id,
                        field_name="city",
                        old_value=user.city,
                        new_value=city,
                    )
                )
            user.city = city
            await self.session.commit()

    async def count_total(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(User))
        return result.scalar_one()

    async def count_banned(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(User).where(User.role == UserRole.banned)
        )
        return result.scalar_one()

    async def list_broadcast_targets(self) -> list[User]:
        result = await self.session.execute(
            select(User).where(User.role != UserRole.banned).order_by(User.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_for_export(self) -> list[User]:
        result = await self.session.execute(
            select(User)
            .options(selectinload(User.profile_changes))
            .order_by(User.created_at.asc(), User.id.asc())
        )
        return list(result.scalars().all())
