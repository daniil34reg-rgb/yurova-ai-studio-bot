import pytest

from bot.gateway_options import configure_all_sections_button
from bot.keyboards import main_menu_kb
from portrait_bot.app_factory import create_context
from portrait_bot.config import Settings
from portrait_bot.models import BotSetting
from portrait_bot.storefront import (
    admin_root_menu,
    all_sections_label,
    gateway_menu,
    seed_storefront_settings,
)


def test_gateway_has_two_configurable_sections() -> None:
    markup = gateway_menu(
        {
            "gateway_store_enabled": "true",
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


def test_store_button_can_be_disabled_on_gateway() -> None:
    markup = gateway_menu(
        {
            "gateway_store_enabled": "false",
            "gateway_store_button": "Акции",
            "gateway_ai_button": "AI-генерация",
        }
    )
    assert [row[0].text for row in markup.inline_keyboard] == ["AI-генерация"]
    assert [row[0].callback_data for row in markup.inline_keyboard] == ["entry:ai"]


def test_admin_root_selects_store_or_generation() -> None:
    markup = admin_root_menu()
    callbacks = [row[0].callback_data for row in markup.inline_keyboard]
    assert callbacks[:2] == ["admin:section:store", "admin:section:ai"]


def test_all_sections_button_can_be_renamed_or_disabled() -> None:
    values = {
        "gateway_all_sections_enabled": "true",
        "gateway_all_sections_label": "🏠 В начало",
    }
    assert all_sections_label(values) == "🏠 В начало"
    values["gateway_all_sections_enabled"] = "false"
    assert all_sections_label(values) is None


def test_store_menu_uses_configured_all_sections_button() -> None:
    try:
        configure_all_sections_button(enabled=True, label="🏠 В начало")
        markup = main_menu_kb()
        assert markup.inline_keyboard[-1][0].text == "🏠 В начало"

        configure_all_sections_button(enabled=False, label="🏠 В начало")
        markup = main_menu_kb()
        assert all(
            button.callback_data != "menu:gateway"
            for row in markup.inline_keyboard
            for button in row
        )
    finally:
        configure_all_sections_button(enabled=True, label="↩️ Все разделы")


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
            store_enabled = await session.get(BotSetting, "gateway_store_enabled")
            assert store_enabled is not None
            assert store_enabled.value == "true"
            back_setting = await session.get(BotSetting, "gateway_all_sections_label")
            assert back_setting is not None
            assert back_setting.value == "↩️ Все разделы"
    finally:
        await context.db.dispose()
