import pytest

from portrait_bot.app_factory import create_context
from portrait_bot.config import Settings
from portrait_bot.models import BotSetting
from portrait_bot.storefront import (
    admin_root_menu,
    gateway_menu,
    seed_storefront_settings,
)


def test_gateway_has_two_configurable_sections() -> None:
    markup = gateway_menu(
        {
            "gateway_store_button": "Купить стикер iPhone 17",
            "gateway_ai_button": "Генерация картинок",
        }
    )
    assert [row[0].text for row in markup.inline_keyboard] == [
        "Купить стикер iPhone 17",
        "Генерация картинок",
    ]
    assert [row[0].callback_data for row in markup.inline_keyboard] == [
        "entry:store",
        "entry:ai",
    ]


def test_admin_root_selects_store_or_generation() -> None:
    markup = admin_root_menu()
    callbacks = [row[0].callback_data for row in markup.inline_keyboard]
    assert callbacks[:2] == ["admin:section:store", "admin:section:ai"]


@pytest.mark.asyncio
async def test_gateway_settings_are_created(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'gateway.db'}",
        storage_dir=tmp_path / "storage",
    )
    context = create_context(settings)
    try:
        await context.db.create_all()
        await seed_storefront_settings(context)
        async with context.db.sessions() as session:
            setting = await session.get(BotSetting, "gateway_store_button")
            assert setting is not None
            assert "iPhone 17" in setting.value
    finally:
        await context.db.dispose()
