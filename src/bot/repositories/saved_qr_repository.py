from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import SavedQR


class SavedQRRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_all(self) -> list[SavedQR]:
        result = await self.session.execute(select(SavedQR).order_by(SavedQR.created_at.desc()))
        return list(result.scalars().all())

    async def get(self, qr_id: int) -> SavedQR | None:
        result = await self.session.execute(select(SavedQR).where(SavedQR.id == qr_id))
        return result.scalar_one_or_none()

    async def create(self, title: str, file_id: str) -> SavedQR:
        qr = SavedQR(title=title, file_id=file_id)
        self.session.add(qr)
        await self.session.commit()
        await self.session.refresh(qr)
        return qr

    async def update_title(self, qr_id: int, title: str) -> SavedQR | None:
        qr = await self.get(qr_id)
        if qr:
            qr.title = title
            await self.session.commit()
            await self.session.refresh(qr)
        return qr

    async def update_photo(self, qr_id: int, file_id: str) -> SavedQR | None:
        qr = await self.get(qr_id)
        if qr:
            qr.file_id = file_id
            await self.session.commit()
            await self.session.refresh(qr)
        return qr

    async def delete(self, qr_id: int) -> bool:
        qr = await self.get(qr_id)
        if not qr:
            return False
        await self.session.delete(qr)
        await self.session.commit()
        return True
