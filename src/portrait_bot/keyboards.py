from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from portrait_bot.models import BotSetting, FeatureFlag, Package, SupportTicket, Template
from portrait_bot.money import format_rub
from portrait_bot.photo_scenarios import PhotoScenario
from portrait_bot.sticker_options import (
    REACTIONS,
    SUPPORTED_STICKER_QUANTITIES,
    StickerVariant,
)


def main_menu(features: Mapping[str, bool]) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    if features.get("sticker_creator", True):
        rows.append([KeyboardButton(text="🎨 Сделать стикеры")])
    creative: list[KeyboardButton] = []
    if features.get("photo_processing", True):
        creative.append(KeyboardButton(text="✨ Обработать фотографию"))
    if features.get("photo_looks", True):
        creative.append(KeyboardButton(text="👑 Создать фотообраз"))
    if creative:
        rows.append(creative)
    if features.get("video_animation", False):
        rows.append([KeyboardButton(text="🎬 Оживить фотографию")])
    optional: list[KeyboardButton] = []
    if features.get("custom_create", False):
        optional.append(KeyboardButton(text="✨ Создать по описанию"))
    if features.get("photo_edit", False):
        optional.append(KeyboardButton(text="✏️ Редактировать фото"))
    if optional:
        rows.append(optional)
    account: list[KeyboardButton] = []
    if features.get("balance", True):
        account.append(KeyboardButton(text="💰 Мой баланс"))
    if features.get("payments", True):
        account.append(KeyboardButton(text="💳 Пополнить баланс"))
    if account:
        rows.append(account)
    history: list[KeyboardButton] = []
    if features.get("orders", True):
        history.append(KeyboardButton(text="🖼 Мои работы"))
    if features.get("support", True):
        history.append(KeyboardButton(text="🛟 Написать в поддержку"))
    if history:
        rows.append(history)
    rows.append([KeyboardButton(text="📄 Документы")])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите действие",
    )


def consent_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Политика конфиденциальности",
                    callback_data="legal:privacy",
                )
            ],
            [InlineKeyboardButton(text="Условия использования", callback_data="legal:terms")],
            [InlineKeyboardButton(text="Согласие на обработку фото", callback_data="legal:photo")],
            [
                InlineKeyboardButton(
                    text="✅ Принимаю",
                    callback_data="consent:accept",
                )
            ],
        ]
    )


def home_actions_menu(features: Mapping[str, bool]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if features.get("sticker_creator", True):
        rows.append(
            [
                InlineKeyboardButton(
                    text="🎨 Сделать стикеры",
                    callback_data="menu:styles",
                )
            ]
        )
    creative: list[InlineKeyboardButton] = []
    if features.get("photo_processing", True):
        creative.append(
            InlineKeyboardButton(
                text="✨ Обработать фотографию",
                callback_data="photo:section:processing",
            )
        )
    if features.get("photo_looks", True):
        creative.append(
            InlineKeyboardButton(
                text="👑 Создать фотообраз",
                callback_data="photo:section:looks",
            )
        )
    if creative:
        rows.append(creative)
    if features.get("video_animation", False):
        rows.append(
            [
                InlineKeyboardButton(
                    text="🎬 Оживить фотографию",
                    callback_data="video:start",
                )
            ]
        )
    account: list[InlineKeyboardButton] = []
    if features.get("balance", True):
        account.append(
            InlineKeyboardButton(
                text="💰 Мой баланс",
                callback_data="menu:balance",
            )
        )
    if features.get("payments", True):
        account.append(
            InlineKeyboardButton(
                text="💳 Пополнить баланс",
                callback_data="menu:buy",
            )
        )
    if account:
        rows.append(account)
    if features.get("support", True):
        rows.append(
            [
                InlineKeyboardButton(
                    text="🛟 Написать в поддержку",
                    callback_data="menu:support",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="📄 Документы", callback_data="menu:documents")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sticker_hub_menu(*, meme_enabled: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="🎨 Обычные стикеры",
                callback_data="stickers:classic",
            )
        ]
    ]
    if meme_enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text="😂 Мем-стикер со своим текстом",
                    callback_data="stickers:meme",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def photo_scenarios_menu(
    scenarios: Sequence[PhotoScenario],
    prices: Mapping[str, Decimal],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for scenario in scenarios:
        price = prices.get(scenario.key)
        title = (
            f"{scenario.title} · {format_rub(price)}"
            if price is not None
            else scenario.title
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=title,
                    callback_data=f"photo:select:{scenario.key}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def photo_options_menu(scenario: PhotoScenario) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    buttons = [
        InlineKeyboardButton(
            text=option.title,
            callback_data=f"photo:option:{scenario.key}:{option.key}",
        )
        for option in scenario.options
    ]
    for index in range(0, len(buttons), 2):
        rows.append(buttons[index : index + 2])
    rows.append(
        [
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"photo:section:{scenario.section}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def documents_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Политика конфиденциальности",
                    callback_data="legal:privacy",
                )
            ],
            [InlineKeyboardButton(text="Условия использования", callback_data="legal:terms")],
            [InlineKeyboardButton(text="Согласие на обработку фото", callback_data="legal:photo")],
        ]
    )


def styles_menu(
    templates: list[Template],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    buttons = []
    for index, template in enumerate(templates, start=1):
        short_title = (
            template.title if len(template.title) <= 14 else template.title[:13].rstrip() + "…"
        )
        buttons.append(
            InlineKeyboardButton(
                text=f"{index}️⃣ {short_title}",
                callback_data=f"style:{template.slug}",
            )
        )
    for index in range(0, len(buttons), 2):
        rows.append(buttons[index : index + 2])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def template_menu(slug: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Выбрать этот стиль", callback_data=f"style:{slug}")],
        ]
    )


def quantity_menu(
    slug: str,
    *,
    prices: Mapping[int, Decimal] | None = None,
) -> InlineKeyboardMarkup:
    prices = prices or {}
    rows: list[list[InlineKeyboardButton]] = []
    for values in ((1, 3), (5, 10)):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{quantity} стик. · {format_rub(prices[quantity])}"
                    if quantity in prices
                    else f"{quantity} стик.",
                    callback_data=f"qty:{slug}:{quantity}",
                )
                for quantity in values
                if quantity in SUPPORTED_STICKER_QUANTITIES
            ]
        )
    rows.append([InlineKeyboardButton(text="◀️ Другой стиль", callback_data="menu:styles")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def variant_menu(slug: str, variants: tuple[StickerVariant, ...]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=variant.title,
                callback_data=f"variant:{slug}:{variant.key}",
            )
        ]
        for variant in variants
    ]
    rows.append([InlineKeyboardButton(text="◀️ Другой образ", callback_data="menu:styles")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reaction_menu(slug: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=f"{reaction.emoji} {reaction.title}",
            callback_data=f"reaction:{slug}:{reaction.key}",
        )
        for reaction in REACTIONS
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="◀️ Изменить количество", callback_data=f"style:{slug}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def caption_menu(slug: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ С надписями",
                    callback_data=f"caption:{slug}:text",
                ),
                InlineKeyboardButton(
                    text="🚫 Без надписей",
                    callback_data=f"caption:{slug}:plain",
                ),
            ],
            [InlineKeyboardButton(text="◀️ Другой образ", callback_data="menu:styles")],
        ]
    )


def packages_menu(packages: list[Package]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for package in packages:
        builder.button(
            text=(
                f"{package.title}: {package.credits} "
                f"{'стикер' if package.credits == 1 else 'стикеров'} — "
                f"{package.amount_rub:.0f} ₽"
            ),
            callback_data=f"buy:{package.code}",
        )
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(
            text="🏠 Главное меню",
            callback_data="menu:main",
        )
    )
    return builder.as_markup()


def payment_menu(url: str, payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=url)],
            [
                InlineKeyboardButton(
                    text="🔄 Проверить оплату",
                    callback_data=f"payment:check:{payment_id}",
                )
            ],
            [InlineKeyboardButton(text="◀️ Назад к тарифам", callback_data="menu:buy")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
        ]
    )


def mock_payment_menu(payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🧪 Подтвердить тестовую оплату",
                    callback_data=f"mockpay:{payment_id}",
                )
            ],
            [InlineKeyboardButton(text="◀️ Назад к тарифам", callback_data="menu:buy")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
        ]
    )


def topup_amounts_menu(
    options: Sequence[tuple[str, Decimal]],
    *,
    custom_enabled: bool,
) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=label,
            callback_data=f"topup:amount:{amount:.2f}",
        )
        for label, amount in options
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    if custom_enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✏️ Другая сумма",
                    callback_data="topup:custom",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_methods_menu(
    amount: Decimal,
    *,
    manual_enabled: bool,
    cloudpayments_enabled: bool,
) -> InlineKeyboardMarkup:
    encoded = f"{amount:.2f}"
    rows: list[list[InlineKeyboardButton]] = []
    if manual_enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🧾 Оплатить вручную",
                    callback_data=f"topup:method:manual:{encoded}",
                )
            ]
        )
    if cloudpayments_enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💳 Оплатить картой",
                    callback_data=f"topup:method:cloudpayments:{encoded}",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:buy")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def manual_payment_menu(payment_id: str, payment_url: str = "") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if payment_url:
        rows.append(
            [InlineKeyboardButton(text="🔗 Перейти к оплате", url=payment_url)]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="✅ Я оплатил",
                callback_data=f"manual:paid:{payment_id}",
            )
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:buy")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_manual_payment_menu(payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"admin:payment:approve:{payment_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"admin:payment:reject:{payment_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👤 Пользователь",
                    callback_data=f"admin:payment:user:{payment_id}",
                )
            ],
        ]
    )


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main")]]
    )


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Функции", callback_data="admin:features")],
            [InlineKeyboardButton(text="🎨 Стили", callback_data="admin:templates")],
            [InlineKeyboardButton(text="💰 Цены и тарифы", callback_data="admin:prices")],
            [InlineKeyboardButton(text="📸 Фото и образы", callback_data="admin:photo")],
            [InlineKeyboardButton(text="🎬 Настройки видео", callback_data="admin:video")],
            [InlineKeyboardButton(text="💳 Способы оплаты", callback_data="admin:payments")],
            [InlineKeyboardButton(text="📝 Тексты бота", callback_data="admin:texts")],
            [
                InlineKeyboardButton(
                    text="🖼 Картинка приветствия",
                    callback_data="admin:welcome_image",
                )
            ],
            [InlineKeyboardButton(text="🛟 Обращения", callback_data="admin:tickets")],
        ]
    )


def admin_photo_menu(
    scenarios: Sequence[PhotoScenario],
    *,
    enabled: Mapping[str, bool],
    prices: Mapping[str, Decimal],
    base_price: Decimal,
    meme_enabled: bool,
    meme_price: Decimal,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"⚙️ Общая цена: {format_rub(base_price)}",
                callback_data="admin:text_edit:photo_base_price_rub",
            )
        ]
    ]
    for scenario in scenarios:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{'🟢' if enabled.get(scenario.key, True) else '⚪️'} {scenario.title}",
                    callback_data=f"admin:photo_toggle:{scenario.key}",
                ),
                InlineKeyboardButton(
                    text=f"💵 {format_rub(prices[scenario.key])}",
                    callback_data=f"admin:text_edit:photo_{scenario.key}_price_rub",
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=f"{'🟢' if meme_enabled else '⚪️'} Мем-стикер",
                callback_data="admin:photo_toggle:meme",
            ),
            InlineKeyboardButton(
                text=f"💵 {format_rub(meme_price)}",
                callback_data="admin:text_edit:meme_sticker_price_rub",
            ),
        ]
    )
    rows.append([InlineKeyboardButton(text="◀️ Админ-панель", callback_data="admin:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_video_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Название",
                    callback_data="admin:text_edit:video_title",
                ),
                InlineKeyboardButton(
                    text="📝 Описание",
                    callback_data="admin:text_edit:video_description",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💵 Цена",
                    callback_data="admin:text_edit:video_price_rub",
                ),
                InlineKeyboardButton(
                    text="⏱ Длительность",
                    callback_data="admin:text_edit:video_duration_seconds",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🤖 Инструкция для ИИ",
                    callback_data="admin:text_edit:video_prompt",
                )
            ],
            [InlineKeyboardButton(text="🧪 Тест видео", callback_data="video:start")],
            [InlineKeyboardButton(text="◀️ Админ-панель", callback_data="admin:main")],
        ]
    )


def admin_payments_menu(
    *,
    manual_enabled: bool,
    cloudpayments_enabled: bool,
    custom_topup_enabled: bool,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{'🟢' if manual_enabled else '⚪️'} Ручное пополнение",
                    callback_data="admin:payment_toggle:manual_payments_enabled",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{'🟢' if cloudpayments_enabled else '⚪️'} CloudPayments",
                    callback_data="admin:payment_toggle:cloudpayments_enabled",
                )
            ],
            [
                InlineKeyboardButton(
                    text=(
                        f"{'🟢' if custom_topup_enabled else '⚪️'} "
                        "Произвольная сумма"
                    ),
                    callback_data="admin:payment_toggle:custom_topup_enabled",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Инструкция",
                    callback_data="admin:text_edit:manual_payment_instructions",
                ),
                InlineKeyboardButton(
                    text="🔗 Ссылка",
                    callback_data="admin:text_edit:manual_payment_url",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🖼 Загрузить QR",
                    callback_data="admin:payment_qr",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💵 Быстрые суммы",
                    callback_data="admin:text_edit:topup_amounts_rub",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬇️ Минимум",
                    callback_data="admin:text_edit:custom_topup_min_rub",
                ),
                InlineKeyboardButton(
                    text="⬆️ Максимум",
                    callback_data="admin:text_edit:custom_topup_max_rub",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📥 Заявки на оплату",
                    callback_data="admin:payments_pending",
                )
            ],
            [InlineKeyboardButton(text="◀️ Админ-панель", callback_data="admin:main")],
        ]
    )


def admin_features_menu(features: Sequence[FeatureFlag]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'🟢' if item.enabled else '⚪️'} {item.title}",
                callback_data=f"admin:feature:{item.key}",
            )
        ]
        for item in features
    ]
    rows.append([InlineKeyboardButton(text="◀️ Админ-панель", callback_data="admin:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_templates_menu(templates: Sequence[Template]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'🟢' if item.active else '⚪️'} {item.title}",
                callback_data=f"admin:template_open:{item.slug}",
            )
        ]
        for item in templates
    ]
    rows.append([InlineKeyboardButton(text="◀️ Админ-панель", callback_data="admin:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_template_menu(template: Template) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{'🟢 Выключить' if template.active else '⚪️ Включить'}",
                    callback_data=f"admin:template_toggle:{template.slug}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Название",
                    callback_data=f"admin:template_edit:{template.slug}:title",
                ),
                InlineKeyboardButton(
                    text="📝 Описание",
                    callback_data=f"admin:template_edit:{template.slug}:description",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🖼 Заменить картинку",
                    callback_data=f"admin:template_edit:{template.slug}:preview",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🤖 Инструкция для ИИ",
                    callback_data=f"admin:template_edit:{template.slug}:prompt",
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ К списку стилей",
                    callback_data="admin:templates",
                )
            ],
        ]
    )


def admin_packages_menu(
    packages: Sequence[Package],
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="⚙️ Базовая цена стикера",
                callback_data="admin:text_edit:sticker_base_price_rub",
            )
        ],
        [
            InlineKeyboardButton(
                text="🔄 Пересчитать автоматические",
                callback_data="admin:packages_recalculate",
            )
        ],
    ] + [
        [
            InlineKeyboardButton(
                text=(
                    f"{'🟢' if item.active else '⚪️'} {item.title}: "
                    f"{item.credits} стик. / {format_rub(item.amount_rub)}"
                ),
                callback_data=f"admin:package_open:{item.code}",
            )
        ]
        for item in packages
    ]
    rows.append([InlineKeyboardButton(text="◀️ Админ-панель", callback_data="admin:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_package_menu(package: Package) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{'🟢 Выключить' if package.active else '⚪️ Включить'}",
                    callback_data=f"admin:package_toggle:{package.code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Название",
                    callback_data=f"admin:package_edit:{package.code}:title",
                ),
                InlineKeyboardButton(
                    text="🧩 Количество стикеров",
                    callback_data=f"admin:package_edit:{package.code}:credits",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💵 Цена в рублях",
                    callback_data=f"admin:package_edit:{package.code}:amount",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Режим цены",
                    callback_data=f"admin:package_mode:{package.code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ К тарифам",
                    callback_data="admin:prices",
                )
            ],
        ]
    )


def admin_package_mode_menu(package: Package) -> InlineKeyboardMarkup:
    labels = {
        "automatic": "Автоматически: количество × база",
        "discount": "От базы со скидкой",
        "custom": "Своя итоговая цена",
    }
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅ ' if package.pricing_mode == mode else ''}{label}",
                callback_data=f"admin:package_set_mode:{package.code}:{mode}",
            )
        ]
        for mode, label in labels.items()
    ]
    if package.pricing_mode == "discount":
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Скидка: {Decimal(package.discount_percent):g}%",
                    callback_data=f"admin:package_edit:{package.code}:discount",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="◀️ К пакету",
                callback_data=f"admin:package_open:{package.code}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_texts_menu(settings: Sequence[BotSetting]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"✏️ {item.title}",
                callback_data=f"admin:text_edit:{item.key}",
            )
        ]
        for item in settings
        if item.key not in {"credit_display_price_rub", "welcome_image_file_id"}
    ]
    rows.append([InlineKeyboardButton(text="◀️ Админ-панель", callback_data="admin:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_tickets_menu(
    tickets: Sequence[SupportTicket],
    *,
    scope: str,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'🆕' if ticket.status == 'new' else '📨'} {ticket.id[:8]}",
                callback_data=f"admin:ticket_open:{ticket.id}",
            )
        ]
        for ticket in tickets
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="📬 Открытые",
                callback_data="admin:tickets:open",
            ),
            InlineKeyboardButton(
                text="🗂 Все",
                callback_data="admin:tickets:all",
            ),
        ]
    )
    rows.append([InlineKeyboardButton(text="◀️ Админ-панель", callback_data="admin:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_ticket_menu(ticket: SupportTicket) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if ticket.status not in {"resolved", "closed"}:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✍️ Ответить",
                    callback_data=f"admin:ticket_reply:{ticket.id}",
                ),
                InlineKeyboardButton(
                    text="✅ Закрыть",
                    callback_data=f"admin:ticket_close:{ticket.id}",
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="◀️ К обращениям",
                callback_data="admin:tickets:open",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def post_generation_menu(features: Mapping[str, bool]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if features.get("sticker_creator", True):
        rows.append(
            [
                InlineKeyboardButton(
                    text="🎨 Создать ещё",
                    callback_data="menu:styles",
                )
            ]
        )
    account: list[InlineKeyboardButton] = []
    if features.get("orders", True):
        account.append(InlineKeyboardButton(text="🖼 Мои работы", callback_data="menu:orders"))
    if features.get("payments", True):
        account.append(InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="menu:buy"))
    if account:
        rows.append(account)
    if features.get("support", True):
        rows.append(
            [
                InlineKeyboardButton(
                    text="🛟 Поддержка",
                    callback_data="menu:support",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
