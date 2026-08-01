from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import PromotionQR


class PromotionQRRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_for_promo(self, promotion_id: int) -> list[PromotionQR]:
        result = await self.session.execute(
            select(PromotionQR)
            .where(PromotionQR.promotion_id == promotion_id)
            .order_by(PromotionQR.sort_order)
        )
        return list(result.scalars().all())

    async def add(self, promotion_id: int, title: str, file_id: str) -> PromotionQR:
        existing = await self.list_for_promo(promotion_id)
        qr = PromotionQR(
            promotion_id=promotion_id,
            title=title,
            file_id=file_id,
            sort_order=len(existing),
        )
        self.session.add(qr)
        await self.session.commit()
        await self.session.refresh(qr)
        return qr

    async def add_link(self, promotion_id: int, title: str, payment_url: str) -> PromotionQR:
        existing = await self.list_for_promo(promotion_id)
        method = PromotionQR(
            promotion_id=promotion_id,
            title=title,
            method_type="link",
            payment_url=payment_url,
            # Empty string also works on older SQLite databases where the
            # legacy file_id column may still have a NOT NULL constraint.
            file_id="",
            sort_order=len(existing),
        )
        self.session.add(method)
        await self.session.commit()
        await self.session.refresh(method)
        return method

    async def get(self, qr_id: int) -> PromotionQR | None:
        result = await self.session.execute(
            select(PromotionQR).where(PromotionQR.id == qr_id)
        )
        return result.scalar_one_or_none()

    async def update_title(self, qr_id: int, title: str) -> PromotionQR | None:
        method = await self.get(qr_id)
        if method:
            method.title = title
            await self.session.commit()
            await self.session.refresh(method)
        return method

    async def update_qr(self, qr_id: int, file_id: str) -> PromotionQR | None:
        method = await self.get(qr_id)
        if method:
            method.method_type = "qr"
            method.file_id = file_id
            method.payment_url = None
            await self.session.commit()
            await self.session.refresh(method)
        return method

    async def update_link(self, qr_id: int, payment_url: str) -> PromotionQR | None:
        method = await self.get(qr_id)
        if method:
            method.method_type = "link"
            method.payment_url = payment_url
            method.file_id = ""
            await self.session.commit()
            await self.session.refresh(method)
        return method

    async def delete(self, qr_id: int) -> bool:
        qr = await self.get(qr_id)
        if not qr:
            return False
        await self.session.delete(qr)
        await self.session.commit()
        return True

    async def count_for_promo(self, promotion_id: int) -> int:
        return len(await self.list_for_promo(promotion_id))

    async def delete_all_for_promo(self, promotion_id: int) -> int:
        result = await self.session.execute(
            delete(PromotionQR).where(PromotionQR.promotion_id == promotion_id)
        )
        await self.session.commit()
        return int(result.rowcount or 0)
