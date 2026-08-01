from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import AccessRecord


class AccessRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: int, access_type: str = "channel") -> AccessRecord:
        record = AccessRecord(user_id=user_id, access_type=access_type)
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def has_active_access(self, user_id: int) -> bool:
        result = await self.session.execute(
            select(AccessRecord).where(
                AccessRecord.user_id == user_id,
                AccessRecord.active == True,
            )
        )
        return result.scalar_one_or_none() is not None

    async def revoke(self, user_id: int) -> None:
        result = await self.session.execute(
            select(AccessRecord).where(
                AccessRecord.user_id == user_id,
                AccessRecord.active == True,
            )
        )
        records = result.scalars().all()
        for r in records:
            r.active = False
        await self.session.commit()
