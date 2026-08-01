from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models import SavedStickerButton, SavedStickerButtonConfig


class SavedStickerButtonConfigRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_all(self) -> list[SavedStickerButtonConfig]:
        result = await self.session.execute(
            select(SavedStickerButtonConfig)
            .options(selectinload(SavedStickerButtonConfig.buttons))
            .order_by(SavedStickerButtonConfig.created_at.desc())
        )
        return list(result.scalars().all())

    async def get(self, config_id: int) -> SavedStickerButtonConfig | None:
        result = await self.session.execute(
            select(SavedStickerButtonConfig)
            .options(selectinload(SavedStickerButtonConfig.buttons))
            .where(SavedStickerButtonConfig.id == config_id)
        )
        return result.scalar_one_or_none()

    async def get_button(self, button_id: int) -> SavedStickerButton | None:
        result = await self.session.execute(
            select(SavedStickerButton).where(SavedStickerButton.id == button_id)
        )
        return result.scalar_one_or_none()

    async def create(self, title: str) -> SavedStickerButtonConfig:
        config = SavedStickerButtonConfig(title=title)
        self.session.add(config)
        await self.session.commit()
        await self.session.refresh(config)
        return config

    async def update_title(self, config_id: int, title: str) -> SavedStickerButtonConfig | None:
        config = await self.get(config_id)
        if config:
            config.title = title
            await self.session.commit()
            await self.session.refresh(config)
        return await self.get(config_id)

    async def add_button(
        self,
        config_id: int,
        label: str,
        sticker_count: int,
        row_width: int = 1,
    ) -> SavedStickerButton | None:
        config = await self.get(config_id)
        if not config:
            return None
        button = SavedStickerButton(
            config_id=config_id,
            label=label,
            sticker_count=sticker_count,
            sort_order=len(config.buttons),
            row_width=row_width,
        )
        self.session.add(button)
        await self.session.commit()
        await self.session.refresh(button)
        return button

    async def update_button(
        self,
        button_id: int,
        label: str,
        sticker_count: int,
        row_width: int | None = None,
    ) -> SavedStickerButton | None:
        button = await self.get_button(button_id)
        if button:
            button.label = label
            button.sticker_count = sticker_count
            if row_width is not None:
                button.row_width = row_width
            await self.session.commit()
            await self.session.refresh(button)
        return button

    async def toggle_button_width(self, button_id: int) -> SavedStickerButton | None:
        button = await self.get_button(button_id)
        if button:
            button.row_width = 2 if button.row_width == 1 else 1
            await self.session.commit()
            await self.session.refresh(button)
        return button

    async def move_button(self, button_id: int, direction: int) -> SavedStickerButton | None:
        button = await self.get_button(button_id)
        if not button:
            return None

        config = await self.get(button.config_id)
        if not config:
            return button

        buttons = list(config.buttons)
        current_index = next((index for index, item in enumerate(buttons) if item.id == button_id), None)
        if current_index is None:
            return button

        target_index = current_index + direction
        if target_index < 0 or target_index >= len(buttons):
            return button

        buttons[current_index], buttons[target_index] = buttons[target_index], buttons[current_index]
        for index, item in enumerate(buttons):
            item.sort_order = index

        await self.session.commit()
        await self.session.refresh(button)
        return button

    async def delete_button(self, button_id: int) -> bool:
        button = await self.get_button(button_id)
        if not button:
            return False
        await self.session.delete(button)
        await self.session.commit()
        return True

    async def delete(self, config_id: int) -> bool:
        config = await self.get(config_id)
        if not config:
            return False
        await self.session.delete(config)
        await self.session.commit()
        return True
