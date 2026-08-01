from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import Promotion


class PromotionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_all(self) -> list[Promotion]:
        result = await self.session.execute(select(Promotion).order_by(Promotion.created_at.desc()))
        return list(result.scalars().all())

    async def get(self, promotion_id: int) -> Promotion | None:
        result = await self.session.execute(select(Promotion).where(Promotion.id == promotion_id))
        return result.scalar_one_or_none()

    async def get_active(self) -> Promotion | None:
        result = await self.session.execute(
            select(Promotion).where(Promotion.is_active == True).order_by(Promotion.created_at.desc())
        )
        return result.scalars().first()

    async def get_all_active(self) -> list[Promotion]:
        result = await self.session.execute(
            select(Promotion).where(Promotion.is_active == True).order_by(Promotion.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(self, title: str, prize_name: str, price_per_sticker: float,
                     photo_file_id: str | None = None) -> Promotion:
        has_active = await self.get_active()
        promotion = Promotion(
            title=title,
            prize_name=prize_name,
            price_per_sticker=price_per_sticker,
            photo_file_id=photo_file_id,
            is_active=has_active is None,
        )
        self.session.add(promotion)
        await self.session.commit()
        await self.session.refresh(promotion)
        return promotion

    async def update_price(self, promotion_id: int, price: float) -> Promotion | None:
        promotion = await self.get(promotion_id)
        if promotion:
            promotion.price_per_sticker = price
            await self.session.commit()
            await self.session.refresh(promotion)
        return promotion

    async def update_title(self, promotion_id: int, title: str) -> Promotion | None:
        promotion = await self.get(promotion_id)
        if promotion:
            promotion.title = title
            await self.session.commit()
            await self.session.refresh(promotion)
        return promotion

    async def update_prize(self, promotion_id: int, prize_name: str) -> Promotion | None:
        promotion = await self.get(promotion_id)
        if promotion:
            promotion.prize_name = prize_name
            await self.session.commit()
            await self.session.refresh(promotion)
        return promotion

    async def update_photo(self, promotion_id: int, photo_file_id: str | None) -> Promotion | None:
        promotion = await self.get(promotion_id)
        if promotion:
            promotion.photo_file_id = photo_file_id
            await self.session.commit()
            await self.session.refresh(promotion)
        return promotion

    async def activate(self, promotion_id: int) -> Promotion | None:
        promotion = await self.get(promotion_id)
        if not promotion:
            return None
        promotion.is_active = True
        await self.session.commit()
        await self.session.refresh(promotion)
        return promotion

    async def deactivate(self, promotion_id: int) -> Promotion | None:
        promotion = await self.get(promotion_id)
        if not promotion:
            return None
        promotion.is_active = False
        await self.session.commit()
        await self.session.refresh(promotion)
        return promotion

    async def delete(self, promotion_id: int) -> bool:
        promotion = await self.get(promotion_id)
        if not promotion:
            return False
        was_active = promotion.is_active
        await self.session.delete(promotion)
        await self.session.commit()
        if was_active:
            promotions = await self.list_all()
            if promotions:
                await self.activate(promotions[0].id)
        return True

    async def update_qr(self, promotion_id: int, qr_file_id: str | None) -> Promotion | None:
        promotion = await self.get(promotion_id)
        if promotion:
            promotion.qr_file_id = qr_file_id
            await self.session.commit()
            await self.session.refresh(promotion)
        return promotion

    async def update_description(self, promotion_id: int, description: str) -> Promotion | None:
        promotion = await self.get(promotion_id)
        if promotion:
            promotion.description = description
            await self.session.commit()
            await self.session.refresh(promotion)
        return promotion

    async def update_payment_text(self, promotion_id: int, text: str | None) -> Promotion | None:
        promotion = await self.get(promotion_id)
        if promotion:
            promotion.payment_text = text
            await self.session.commit()
            await self.session.refresh(promotion)
        return promotion

async def update_price(self, promotion_id: int, price: float) -> Promotion | None:
    promotion = await self.get(promotion_id)
    if promotion:
        promotion.price_per_sticker = price
        await self.session.commit()
        await self.session.refresh(promotion)
    return promotion