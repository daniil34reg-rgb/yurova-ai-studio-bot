from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import SentQRMessage


class SentQRMessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, chat_id: int, message_id: int, delete_after: datetime) -> SentQRMessage:
        record = SentQRMessage(
            chat_id=chat_id,
            message_id=message_id,
            delete_after=delete_after,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def list_due(self, now: datetime, limit: int = 100) -> list[SentQRMessage]:
        result = await self.session.execute(
            select(SentQRMessage)
            .where(SentQRMessage.delete_after <= now)
            .order_by(SentQRMessage.delete_after, SentQRMessage.id)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete_ids(self, record_ids: list[int]) -> int:
        if not record_ids:
            return 0
        result = await self.session.execute(
            delete(SentQRMessage).where(SentQRMessage.id.in_(record_ids))
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    async def delete_all(self) -> int:
        result = await self.session.execute(delete(SentQRMessage))
        await self.session.commit()
        return int(result.rowcount or 0)
