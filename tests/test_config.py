from pathlib import Path

import pytest

from portrait_bot.config import Settings


def test_admin_ids_are_parsed() -> None:
    settings = Settings(
        _env_file=None,
        admin_ids="10, 20",
        templates_file=Path("config/templates.yaml"),
        packages_file=Path("config/packages.yaml"),
    )
    assert settings.admin_ids == frozenset({10, 20})


def test_single_admin_id_and_empty_support_chat_are_parsed_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_IDS", "982322507")
    monkeypatch.setenv("SUPPORT_CHAT_ID", "")

    settings = Settings(
        _env_file=None,
        templates_file=Path("config/templates.yaml"),
        packages_file=Path("config/packages.yaml"),
    )

    assert settings.admin_ids == frozenset({982322507})
    assert settings.support_chat_id is None


def test_bothost_bot_token_alias_is_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("BOT_TOKEN", "123456:bothost-token")

    settings = Settings(_env_file=None)

    assert settings.telegram_bot_token == "123456:bothost-token"


def test_openai_key_is_required() -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        Settings(_env_file=None, image_provider="openai")


def test_cloudpayments_credentials_are_required() -> None:
    with pytest.raises(ValueError, match="CLOUDPAYMENTS"):
        Settings(_env_file=None, payment_provider="cloudpayments")
