from decimal import Decimal

import pytest

from portrait_bot.config import Settings
from portrait_bot.keyboards import home_actions_menu, topup_amounts_menu
from portrait_bot.money import format_rub, parse_amount_list, parse_money


def test_ruble_format_hides_zero_kopecks() -> None:
    assert format_rub(Decimal("399.00")) == "399 ₽"
    assert format_rub(Decimal("399.50")) == "399,50 ₽"
    assert format_rub(Decimal("12399.99")) == "12 399,99 ₽"


def test_money_parser_accepts_comma_and_rejects_invalid_values() -> None:
    assert parse_money(" 299,90 ") == Decimal("299.90")
    assert parse_amount_list("99; 500, 99") == (
        Decimal("99.00"),
        Decimal("500.00"),
    )
    with pytest.raises(ValueError):
        parse_money("не сумма")


def test_legacy_video_model_is_normalized() -> None:
    settings = Settings(_env_file=None, video_model="wan2.5")
    assert settings.video_model == "wan-2.7"


def test_topup_menu_uses_product_labels_and_custom_amount() -> None:
    keyboard = topup_amounts_menu(
        [
            ("1 стик. — 99 ₽", Decimal("99")),
            ("Видео — 200 ₽", Decimal("200")),
        ],
        custom_enabled=True,
    )
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert "1 стик. — 99 ₽" in labels
    assert "Видео — 200 ₽" in labels
    assert "✏️ Другая сумма" in labels
    assert "topup:amount:99.00" in callbacks


def test_home_actions_contains_video_once() -> None:
    keyboard = home_actions_menu(
        {
            "sticker_creator": True,
            "video_animation": True,
            "balance": True,
            "payments": True,
            "support": True,
        }
    )
    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    ]
    assert callbacks.count("video:start") == 1
