from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from portrait_bot.models import BotSetting, FeatureFlag, Package, Template
from portrait_bot.photo_scenarios import (
    MEME_PROMPT,
    PHOTO_SCENARIOS,
    enabled_setting_key,
    price_setting_key,
    prompt_setting_key,
)

DEFAULT_SETTINGS: tuple[dict[str, str], ...] = (
    {
        "key": "welcome_message",
        "title": "Приветственное сообщение",
        "value": (
            "Добро пожаловать в <b>Yurova AI Studio</b> — здесь фотографии "
            "превращаются в мультяшные Telegram-стикеры."
        ),
    },
    {
        "key": "consent_intro",
        "title": "Сообщение перед согласием",
        "value": "Перед началом ознакомьтесь с документами и примите условия.",
    },
    {
        "key": "post_generation_message",
        "title": "Сообщение после заказа",
        "value": "Что хотите сделать дальше?",
    },
    {
        "key": "sticker_base_price_rub",
        "title": "Базовая цена одного стикера, ₽",
        "value": "99",
    },
    {
        "key": "credit_display_price_rub",
        "title": "Устаревшая цена кредита",
        "value": "0",
    },
    {
        "key": "video_price_rub",
        "title": "Цена оживления фотографии, ₽",
        "value": "200",
    },
    {
        "key": "video_title",
        "title": "Название функции видео",
        "value": "Оживить фотографию",
    },
    {
        "key": "video_description",
        "title": "Описание функции видео",
        "value": "Создам вертикальное видео примерно на 5 секунд, сохранив лица и одежду.",
    },
    {
        "key": "video_prompt",
        "title": "Инструкция для генерации видео",
        "value": (
            "Animate the uploaded photo into a natural five-second cinematic shot. "
            "Preserve every person's identity, face, clothing and the number of people. "
            "Use subtle natural motion, stable camera, realistic anatomy and no new text."
        ),
    },
    {
        "key": "video_duration_seconds",
        "title": "Длительность видео, секунд",
        "value": "5",
    },
    {
        "key": "manual_payments_enabled",
        "title": "Ручное пополнение",
        "value": "true",
    },
    {
        "key": "cloudpayments_enabled",
        "title": "CloudPayments",
        "value": "false",
    },
    {
        "key": "manual_payment_instructions",
        "title": "Инструкция ручной оплаты",
        "value": (
            "Оплатите выбранную сумму по ссылке или QR-коду, затем нажмите "
            "«Я оплатил» и отправьте чек. Баланс начислит администратор после проверки."
        ),
    },
    {
        "key": "manual_payment_url",
        "title": "Ссылка ручной оплаты",
        "value": "",
    },
    {
        "key": "manual_payment_qr_path",
        "title": "QR-код ручной оплаты",
        "value": "",
    },
    {
        "key": "topup_amounts_rub",
        "title": "Быстрые суммы пополнения",
        "value": "99,500,1000,2000,5000",
    },
    {
        "key": "custom_topup_enabled",
        "title": "Произвольная сумма пополнения",
        "value": "true",
    },
    {
        "key": "custom_topup_min_rub",
        "title": "Минимальная сумма пополнения, ₽",
        "value": "99",
    },
    {
        "key": "custom_topup_max_rub",
        "title": "Максимальная сумма пополнения, ₽",
        "value": "100000",
    },
)

DEFAULT_SETTINGS = DEFAULT_SETTINGS + (
    {
        "key": "photo_base_price_rub",
        "title": "Общая цена обработки или фотообраза, ₽",
        "value": "99",
    },
    {
        "key": "meme_sticker_enabled",
        "title": "Мем-стикер включён",
        "value": "true",
    },
    {
        "key": "meme_sticker_price_rub",
        "title": "Цена мем-стикера, ₽ (0 — базовая цена стикера)",
        "value": "0",
    },
    {
        "key": "meme_sticker_prompt",
        "title": "Инструкция ИИ для мем-стикера",
        "value": MEME_PROMPT,
    },
) + tuple(
    setting
    for scenario in PHOTO_SCENARIOS
    for setting in (
        {
            "key": enabled_setting_key(scenario.key),
            "title": f"{scenario.title}: функция включена",
            "value": "true",
        },
        {
            "key": price_setting_key(scenario.key),
            "title": f"{scenario.title}: своя цена, ₽ (0 — общая)",
            "value": "0",
        },
        {
            "key": prompt_setting_key(scenario.key),
            "title": f"{scenario.title}: инструкция ИИ",
            "value": scenario.prompt,
        },
    )
)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping in {path}")
    return cast(dict[str, Any], value)


async def seed_catalog(
    session: AsyncSession,
    templates_file: Path,
    packages_file: Path,
    features_file: Path | None = None,
) -> None:
    templates_data = cast(Sequence[object], _load_yaml(templates_file).get("templates", []))
    packages_data = cast(Sequence[object], _load_yaml(packages_file).get("packages", []))
    features_data = cast(
        Sequence[object],
        _load_yaml(features_file).get("features", []) if features_file else [],
    )

    for item in templates_data:
        if not isinstance(item, dict):
            continue
        slug = str(item["slug"])
        current = await session.scalar(select(Template).where(Template.slug == slug))
        values = {
            "title": str(item["title"]),
            "description": str(item["description"]),
            "category": str(item["category"]),
            "prompt": str(item["prompt"]),
            "preview_path": (str(item["preview_path"]) if item.get("preview_path") else None),
            "credits": int(item.get("credits", 1)),
            "active": bool(item.get("active", True)),
            "sort_order": int(item.get("sort_order", 100)),
            "version": int(item.get("version", 1)),
        }
        if current:
            incoming_version = int(str(values.pop("version")))
            if incoming_version > current.version:
                for key, value in values.items():
                    setattr(current, key, value)
                current.version = incoming_version
            elif current.preview_path is None and values["preview_path"] is not None:
                current.preview_path = str(values["preview_path"])
        else:
            session.add(Template(slug=slug, **values))

    for item in packages_data:
        if not isinstance(item, dict):
            continue
        code = str(item["code"])
        current = await session.scalar(select(Package).where(Package.code == code))
        package_values = {
            "title": str(item["title"]),
            "credits": int(item["credits"]),
            "amount_rub": Decimal(str(item["amount_rub"])),
            "pricing_mode": str(item.get("pricing_mode", "custom")),
            "discount_percent": Decimal(str(item.get("discount_percent", 0))),
            "active": bool(item.get("active", True)),
            "sort_order": int(item.get("sort_order", 100)),
            "version": int(item.get("version", 1)),
        }
        if current:
            incoming_version = int(str(package_values.pop("version")))
            if incoming_version > current.version:
                current.title = str(package_values["title"])
                current.credits = int(str(package_values["credits"]))
                current.amount_rub = Decimal(str(package_values["amount_rub"]))
                current.pricing_mode = str(package_values["pricing_mode"])
                current.discount_percent = Decimal(
                    str(package_values["discount_percent"])
                )
                current.active = bool(package_values["active"])
                current.sort_order = int(str(package_values["sort_order"]))
                current.version = incoming_version
        else:
            session.add(Package(code=code, **package_values))

    for item in features_data:
        if not isinstance(item, dict):
            continue
        key = str(item["key"])
        feature_flag = await session.get(FeatureFlag, key)
        if feature_flag:
            feature_flag.title = str(item["title"])
            feature_flag.sort_order = int(item.get("sort_order", 100))
        else:
            session.add(
                FeatureFlag(
                    key=key,
                    title=str(item["title"]),
                    enabled=bool(item.get("enabled", False)),
                    sort_order=int(item.get("sort_order", 100)),
                )
            )

    for item in DEFAULT_SETTINGS:
        if not await session.get(BotSetting, item["key"]):
            session.add(BotSetting(**item))

    await session.commit()
