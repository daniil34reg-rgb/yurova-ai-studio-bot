from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import StickerButton


class StickerButtonRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_for_promo(self, promotion_id: int) -> list[StickerButton]:
        result = await self.session.execute(
            select(StickerButton)
            .where(StickerButton.promotion_id == promotion_id)
            .order_by(StickerButton.sort_order)
        )
        return list(result.scalars().all())

    async def get(self, btn_id: int) -> StickerButton | None:
        result = await self.session.execute(
            select(StickerButton).where(StickerButton.id == btn_id)
        )
        return result.scalar_one_or_none()

    async def add(self, promotion_id: int, label: str, sticker_count: int, row_width: int = 1) -> StickerButton:
        existing = await self.list_for_promo(promotion_id)
        btn = StickerButton(
            promotion_id=promotion_id,
            label=label,
            sticker_count=sticker_count,
            issued_count=sticker_count,
            sort_order=len(existing),
            row_width=row_width,
        )
        self.session.add(btn)
        await self.session.commit()
        await self.session.refresh(btn)
        return btn

    async def update(
        self,
        btn_id: int,
        label: str,
        sticker_count: int,
        row_width: int | None = None,
    ) -> StickerButton | None:
        btn = await self.get(btn_id)
        if btn:
            if btn.issued_count is None or btn.issued_count == btn.sticker_count:
                btn.issued_count = sticker_count
            btn.label = label
            btn.sticker_count = sticker_count
            if row_width is not None:
                btn.row_width = row_width
            await self.session.commit()
            await self.session.refresh(btn)
        return btn

    async def toggle_width(self, btn_id: int) -> StickerButton | None:
        btn = await self.get(btn_id)
        if btn:
            btn.row_width = 2 if btn.row_width == 1 else 1
            await self.session.commit()
            await self.session.refresh(btn)
        return btn

    async def move(self, btn_id: int, direction: int) -> StickerButton | None:
        btn = await self.get(btn_id)
        if not btn:
            return None

        buttons = await self.list_for_promo(btn.promotion_id)
        current_index = next((index for index, item in enumerate(buttons) if item.id == btn_id), None)
        if current_index is None:
            return btn

        target_index = current_index + direction
        if target_index < 0 or target_index >= len(buttons):
            return btn

        buttons[current_index], buttons[target_index] = buttons[target_index], buttons[current_index]
        for index, item in enumerate(buttons):
            item.sort_order = index

        await self.session.commit()
        await self.session.refresh(btn)
        return btn

    async def delete(self, btn_id: int) -> bool:
        btn = await self.get(btn_id)
        if not btn:
            return False
        await self.session.delete(btn)
        await self.session.commit()
        return True

    async def replace_for_promo(self, promotion_id: int, buttons: list) -> list[StickerButton]:
        await self.session.execute(delete(StickerButton).where(StickerButton.promotion_id == promotion_id))
        for index, btn in enumerate(buttons):
            self.session.add(
                StickerButton(
                    promotion_id=promotion_id,
                    label=btn.label,
                    sticker_count=btn.sticker_count,
                    issued_count=getattr(btn, "issued_count", None) or btn.sticker_count,
                    sort_order=index,
                    row_width=getattr(btn, "row_width", 1),
                )
            )
        await self.session.commit()
        return await self.list_for_promo(promotion_id)
