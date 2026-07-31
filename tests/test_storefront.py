from decimal import Decimal

import pytest
from sqlalchemy import select

from portrait_bot.app_factory import create_context
from portrait_bot.config import Settings
from portrait_bot.models import BotSetting, StoreOrder, StoreProfile
from portrait_bot.storefront import gateway_menu, parse_store_packages, seed_storefront_settings


def test_store_packages_are_parsed_in_configured_order() -> None:
    assert parse_store_packages("1:99, 5:450;10:800") == [
        (1, Decimal("99.00")),
        (5, Decimal("450.00")),
        (10, Decimal("800.00")),
    ]


@pytest.mark.parametrize(
    "raw",
    ["", "1", "0:99", "1:0", "1:99,1:100", "abc:99"],
)
def test_invalid_store_packages_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_store_packages(raw)


def test_gateway_buttons_are_configurable() -> None:
    markup = gateway_menu(
        {
            "store_enabled": "true",
            "gateway_store_button": "Купить стикер iPhone 17",
            "gateway_ai_button": "Генерация картинок",
        }
    )
    assert [row[0].text for row in markup.inline_keyboard] == [
        "Купить стикер iPhone 17",
        "Генерация картинок",
    ]


def test_store_button_can_be_hidden() -> None:
    markup = gateway_menu(
        {
            "store_enabled": "false",
            "gateway_store_button": "Магазин",
            "gateway_ai_button": "AI",
        }
    )
    assert [row[0].callback_data for row in markup.inline_keyboard] == ["entry:ai"]


@pytest.mark.asyncio
async def test_storefront_schema_and_settings_are_created(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'storefront.db'}",
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
            assert list((await session.scalars(select(StoreProfile))).all()) == []
            assert list((await session.scalars(select(StoreOrder))).all()) == []
    finally:
        await context.db.dispose()
