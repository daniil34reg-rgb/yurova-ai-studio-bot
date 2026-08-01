from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from io import BytesIO
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonCommands,
    Message,
    ReplyKeyboardMarkup,
)
from sqlalchemy import func, select

from bot.database import async_session_maker as store_session_maker
from bot.handlers import setup_routers as setup_store_routers
from bot.middlewares import DatabaseMiddleware as StoreDatabaseMiddleware
from portrait_bot.access_codes import (
    access_code_report_rows,
    access_code_stats,
    build_access_codes_workbook,
    create_access_code_batch,
    recent_access_codes,
    redeem_access_code,
)
from portrait_bot.context import AppContext
from portrait_bot.generation_metadata import attach_local_caption
from portrait_bot.keyboards import (
    access_code_admin_menu,
    access_code_expiry_menu,
    admin_documents_menu,
    admin_features_menu,
    admin_manual_payment_menu,
    admin_menu,
    admin_package_menu,
    admin_package_mode_menu,
    admin_packages_menu,
    admin_payments_menu,
    admin_photo_menu,
    admin_template_menu,
    admin_templates_menu,
    admin_texts_menu,
    admin_ticket_menu,
    admin_tickets_menu,
    admin_video_menu,
    back_menu,
    caption_menu,
    consent_menu,
    documents_menu,
    home_actions_menu,
    main_menu,
    manual_payment_menu,
    mock_payment_menu,
    packages_menu,
    payment_menu,
    payment_methods_menu,
    photo_options_menu,
    photo_scenarios_menu,
    quantity_menu,
    reaction_menu,
    sticker_hub_menu,
    styles_menu,
    topup_amounts_menu,
    variant_menu,
)
from portrait_bot.legal import photo_consent_text, privacy_text, terms_text
from portrait_bot.models import (
    AuditLog,
    BotSetting,
    Consent,
    FeatureFlag,
    Generation,
    Package,
    Payment,
    PaymentStatus,
    SupportTicket,
    Template,
    TicketStatus,
    User,
)
from portrait_bot.money import format_rub, parse_amount_list, parse_money, setting_enabled
from portrait_bot.photo_scenarios import (
    MEME_PROMPT,
    PHOTO_SCENARIOS,
    enabled_setting_key,
    option_by_key,
    price_setting_key,
    prompt_setting_key,
    scenario_by_key,
    scenarios_for_section,
)
from portrait_bot.services import (
    add_wallet_entry,
    balance,
    create_generation,
    create_payment,
    create_ticket,
    create_topup_payment,
    get_or_create_user,
    get_setting,
    mark_payment_paid,
    package_price,
    recalculate_package_prices,
    wallet_balance,
)
from portrait_bot.sticker_options import (
    SUPPORTED_STICKER_QUANTITIES,
    collection_variants,
    reaction_by_key,
    variant_by_key,
)
from portrait_bot.storefront import (
    GatewayButtonFilter,
    all_sections_label,
    gateway_menu,
    store_settings,
)
from portrait_bot.storefront import router as storefront_router
from portrait_bot.style_grid import build_style_grid


class CreateFlow(StatesGroup):
    awaiting_prompt = State()
    awaiting_variant = State()
    awaiting_quantity = State()
    awaiting_reaction = State()
    awaiting_caption = State()
    awaiting_photo = State()


class SupportFlow(StatesGroup):
    awaiting_message = State()


class VideoFlow(StatesGroup):
    awaiting_photo = State()


class PhotoFlow(StatesGroup):
    awaiting_option = State()
    awaiting_text = State()
    awaiting_photo = State()


class PaymentFlow(StatesGroup):
    awaiting_custom_amount = State()
    awaiting_proof = State()


class AccessFlow(StatesGroup):
    awaiting_code = State()


class AdminAccessCodeFlow(StatesGroup):
    awaiting_count = State()
    awaiting_accesses = State()


class AdminFlow(StatesGroup):
    awaiting_template_value = State()
    awaiting_template_preview = State()
    awaiting_package_value = State()
    awaiting_setting_value = State()
    awaiting_welcome_image = State()
    awaiting_document_value = State()
    awaiting_ticket_reply = State()
    awaiting_payment_qr = State()


router = Router()

CONSENT_VERSION = "2"
TICKET_STATUS_LABELS = {
    TicketStatus.NEW.value: "Новое",
    TicketStatus.IN_PROGRESS.value: "В работе",
    TicketStatus.WAITING_USER.value: "Ожидает пользователя",
    TicketStatus.RESOLVED.value: "Решено",
    TicketStatus.CLOSED.value: "Закрыто",
}


async def _features(context: AppContext) -> dict[str, bool]:
    async with context.db.sessions() as session:
        flags = list(
            (await session.scalars(select(FeatureFlag).order_by(FeatureFlag.sort_order))).all()
        )
    return {flag.key: flag.enabled for flag in flags}


async def _main_menu(context: AppContext) -> ReplyKeyboardMarkup:
    values = await store_settings(context)
    return main_menu(
        await _features(context),
        all_sections_label=all_sections_label(values),
    )


async def _home_actions_menu(context: AppContext) -> InlineKeyboardMarkup:
    values = await store_settings(context)
    return home_actions_menu(
        await _features(context),
        all_sections_label=all_sections_label(values),
    )


async def _setting(context: AppContext, key: str, default: str = "") -> str:
    async with context.db.sessions() as session:
        item = await session.get(BotSetting, key)
    return item.value if item else default


async def _settings_map(context: AppContext, keys: set[str]) -> dict[str, str]:
    async with context.db.sessions() as session:
        items = list(
            (await session.scalars(select(BotSetting).where(BotSetting.key.in_(keys)))).all()
        )
    return {item.key: item.value for item in items}


LEGAL_DOCUMENTS = {
    "privacy": ("legal_privacy_text", "Политика конфиденциальности"),
    "terms": ("legal_terms_text", "Условия использования"),
    "photo": ("legal_photo_consent_text", "Согласие на обработку фото"),
}


def _generation_charge_text(generation: Generation) -> str:
    if generation.credits > 0:
        amount = generation.credits
        if amount % 10 == 1 and amount % 100 != 11:
            label = "доступ"
        elif amount % 10 in {2, 3, 4} and amount % 100 not in {12, 13, 14}:
            label = "доступа"
        else:
            label = "доступов"
        return f"{generation.credits} {label} к генерации"
    return format_rub(generation.price_rub)


def _default_legal_text(context: AppContext, document: str) -> str:
    defaults = {
        "privacy": privacy_text(context.settings),
        "terms": terms_text(context.settings),
        "photo": photo_consent_text(context.settings),
    }
    return defaults.get(document, "Документ не найден.")


async def _legal_text(context: AppContext, document: str) -> str:
    definition = LEGAL_DOCUMENTS.get(document)
    if not definition:
        return "Документ не найден."
    value = await _setting(context, definition[0])
    return value or _default_legal_text(context, document)


async def _photo_price(context: AppContext, scenario_key: str) -> Decimal:
    values = await _settings_map(
        context,
        {"photo_base_price_rub", price_setting_key(scenario_key)},
    )
    base = parse_money(values.get("photo_base_price_rub", "99"))
    override = parse_money(values.get(price_setting_key(scenario_key), "0"))
    return override if override > 0 else base


async def _meme_price(context: AppContext) -> Decimal:
    values = await _settings_map(
        context,
        {"meme_sticker_price_rub", "sticker_base_price_rub"},
    )
    override = parse_money(values.get("meme_sticker_price_rub", "0"))
    return (
        override
        if override > 0
        else parse_money(values.get("sticker_base_price_rub", "99"))
    )


async def _sticker_prices(context: AppContext) -> dict[int, Decimal]:
    async with context.db.sessions() as session:
        packages = list(
            (
                await session.scalars(
                    select(Package).where(Package.active.is_(True)).order_by(Package.amount_rub)
                )
            ).all()
        )
        return {
            package.credits: await package_price(session, package)
            for package in packages
            if package.credits in SUPPORTED_STICKER_QUANTITIES
        }


async def _feature_enabled(context: AppContext, key: str) -> bool:
    async with context.db.sessions() as session:
        flag = await session.get(FeatureFlag, key)
    return bool(flag and flag.enabled)


async def _user(message: Message, context: AppContext) -> User:
    if not message.from_user:
        raise RuntimeError("Telegram user is missing")
    async with context.db.sessions() as session:
        return await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            language_code=message.from_user.language_code,
            welcome_credits=context.settings.welcome_credits,
            welcome_balance_rub=context.settings.welcome_balance_rub,
        )


async def _has_consent(context: AppContext, user_id: str) -> bool:
    async with context.db.sessions() as session:
        count = await session.scalar(
            select(func.count(Consent.id)).where(
                Consent.user_id == user_id,
                Consent.document_type.in_({"privacy", "terms", "photo_processing"}),
                Consent.version == CONSENT_VERSION,
            )
        )
        return int(count or 0) == 3


async def _begin_support(
    event: Message | CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not await _feature_enabled(context, "support"):
        await event.answer("Поддержка временно недоступна.")
        return
    await state.set_state(SupportFlow.awaiting_message)
    await state.update_data(category="support")
    text = (
        "Напишите вопрос одним сообщением. Если обращение связано с оплатой или "
        "генерацией, укажите номер заказа."
    )
    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            await event.message.answer(text)
    else:
        await event.answer(text)


async def _activate_deeplink(
    message: Message,
    state: FSMContext,
    context: AppContext,
    payload: str,
) -> bool:
    if not payload.startswith("st_"):
        return False
    slug = payload.removeprefix("st_")
    async with context.db.sessions() as session:
        template = await session.scalar(
            select(Template).where(Template.slug == slug, Template.active.is_(True))
        )
    if not template:
        return False
    await state.update_data(
        mode="template",
        template_slug=template.slug,
        prompt=template.prompt,
    )
    variants = collection_variants(template.slug)
    if variants:
        await state.set_state(CreateFlow.awaiting_variant)
        await message.answer(
            f"✨ <b>{template.title}</b>\n\n{template.description}\n\nВыберите вариант образа:",
            reply_markup=variant_menu(template.slug, variants),
        )
    else:
        await state.set_state(CreateFlow.awaiting_quantity)
        await message.answer(
            f"✨ <b>{template.title}</b>\n\n{template.description}\n\nСколько стикеров создать?",
            reply_markup=quantity_menu(
                template.slug,
                prices=await _sticker_prices(context),
            ),
        )
    return True


async def _send_welcome(message: Message, context: AppContext) -> None:
    preview = Path("assets/welcome/welcome-hero-v1.png")
    welcome_image_file_id = await _setting(context, "welcome_image_file_id")
    welcome_text = await _setting(
        context,
        "welcome_message",
        (
            "Добро пожаловать в <b>Yurova AI Studio</b> — здесь фотографии "
            "превращаются в мультяшные Telegram-стикеры."
        ),
    )
    main_menu = await _main_menu(context)
    if welcome_image_file_id:
        try:
            if len(welcome_text) <= 900:
                await message.answer_photo(
                    welcome_image_file_id,
                    caption=welcome_text,
                    reply_markup=main_menu,
                )
            else:
                await message.answer_photo(welcome_image_file_id)
                await message.answer(welcome_text, reply_markup=main_menu)
            await message.answer(
                "Что хотите сделать?",
                reply_markup=await _home_actions_menu(context),
            )
            return
        except TelegramBadRequest:
            # The stored Telegram file_id can become invalid after changing the bot token.
            # In that case, keep /start working and fall back to the bundled image.
            pass

    preview_exists = await asyncio.to_thread(preview.exists)
    if preview_exists and len(welcome_text) <= 900:
        await message.answer_photo(
            FSInputFile(preview),
            caption=welcome_text,
            reply_markup=main_menu,
        )
    else:
        if preview_exists:
            await message.answer_photo(FSInputFile(preview))
        await message.answer(welcome_text, reply_markup=main_menu)
    await message.answer(
        "Что хотите сделать?",
        reply_markup=await _home_actions_menu(context),
    )


async def _send_gateway(message: Message, context: AppContext) -> None:
    preview = Path("assets/welcome/welcome-hero-v1.png")
    welcome_image_file_id = await _setting(context, "welcome_image_file_id")
    welcome_text = await _setting(
        context,
        "welcome_message",
        (
            "Добро пожаловать в <b>Yurova AI Studio</b>. Здесь можно купить "
            "стикер действующей акции или создать изображение с помощью AI."
        ),
    )
    values = await store_settings(context)
    caption = f"{welcome_text}\n\n<b>{escape(values['gateway_message'])}</b>"
    markup = gateway_menu(values)
    if welcome_image_file_id:
        try:
            if len(caption) <= 900:
                await message.answer_photo(
                    welcome_image_file_id,
                    caption=caption,
                    reply_markup=markup,
                )
            else:
                await message.answer_photo(welcome_image_file_id)
                await message.answer(caption, reply_markup=markup)
            return
        except TelegramBadRequest:
            pass
    preview_exists = await asyncio.to_thread(preview.exists)
    if preview_exists and len(caption) <= 900:
        await message.answer_photo(FSInputFile(preview), caption=caption, reply_markup=markup)
    else:
        if preview_exists:
            await message.answer_photo(FSInputFile(preview))
        await message.answer(caption, reply_markup=markup)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, context: AppContext) -> None:
    await state.clear()
    payload = ""
    if message.text and " " in message.text:
        payload = message.text.split(" ", 1)[1].strip()
    if payload == "support":
        await _begin_support(message, state, context)
        return
    user = await _user(message, context)
    if not await _has_consent(context, user.id):
        await message.answer(
            await _setting(
                context,
                "consent_intro",
                "Перед началом ознакомьтесь с документами и примите условия.",
            ),
            reply_markup=consent_menu(),
        )
        if payload.startswith("st_"):
            await state.update_data(pending_deeplink=payload)
        return
    if await _activate_deeplink(message, state, context, payload):
        return
    await _send_gateway(message, context)


@router.callback_query(F.data == "consent:accept")
async def accept_consent(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not callback.from_user:
        return
    async with context.db.sessions() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            language_code=callback.from_user.language_code,
        )
        existing = set(
            (
                await session.scalars(
                    select(Consent.document_type).where(
                        Consent.user_id == user.id,
                        Consent.version == CONSENT_VERSION,
                    )
                )
            ).all()
        )
        for document_type in (
            "privacy",
            "terms",
            "photo_processing",
        ):
            if document_type not in existing:
                session.add(
                    Consent(
                        user_id=user.id,
                        document_type=document_type,
                        version=CONSENT_VERSION,
                    )
                )
        await session.commit()
    await callback.answer("Согласие сохранено")
    data = await state.get_data()
    if pending := data.get("pending_deeplink"):
        await state.clear()
        if isinstance(callback.message, Message):
            await _activate_deeplink(
                callback.message,
                state,
                context,
                str(pending),
            )
        return
    if isinstance(callback.message, Message):
        await state.clear()
        await callback.message.answer("Согласие принято ✅")
        await _send_gateway(callback.message, context)


@router.callback_query(F.data == "entry:ai")
async def enter_ai(callback: CallbackQuery, context: AppContext) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await _send_welcome(callback.message, context)


@router.callback_query(F.data == "menu:gateway")
@router.message(GatewayButtonFilter())
async def show_gateway(
    event: Message | CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    await state.clear()
    if isinstance(event, CallbackQuery):
        await event.answer()
        if isinstance(event.message, Message):
            await _send_gateway(event.message, context)
    else:
        await _send_gateway(event, context)


@router.message(Command("help"))
async def help_command(message: Message, context: AppContext) -> None:
    await message.answer(
        "Выберите стиль стикеров, количество и отправьте одну чёткую фотографию. "
        "При технической ошибке списанная сумма возвращается на баланс автоматически.",
        reply_markup=await _main_menu(context),
    )


@router.message(Command("privacy"))
async def privacy_command(message: Message, context: AppContext) -> None:
    await message.answer(await _legal_text(context, "privacy"))


@router.message(Command("terms"))
async def terms_command(message: Message, context: AppContext) -> None:
    await message.answer(await _legal_text(context, "terms"))


@router.message(F.text == "📄 Документы")
async def documents(message: Message) -> None:
    await message.answer("Выберите документ:", reply_markup=documents_menu())


@router.callback_query(F.data == "menu:documents")
async def documents_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer("Выберите документ:", reply_markup=documents_menu())


@router.callback_query(F.data.startswith("legal:"))
async def legal_document(callback: CallbackQuery, context: AppContext) -> None:
    document = (callback.data or "").split(":", 1)[1]
    await callback.answer()
    if callback.message:
        await callback.message.answer(await _legal_text(context, document))


@router.message(Command("delete_me"))
async def delete_me(message: Message, context: AppContext) -> None:
    if not await _feature_enabled(context, "data_deletion"):
        await message.answer(
            f"Запрос на удаление данных можно направить через поддержку или "
            f"{context.settings.support_email}."
        )
        return
    await message.answer(
        "Удалить загруженные фотографии, результаты и персональные данные профиля? "
        "Финансовые записи сохранятся в обезличенном виде.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Удалить мои данные",
                        callback_data="delete:confirm",
                    )
                ],
                [InlineKeyboardButton(text="Отмена", callback_data="menu:main")],
            ]
        ),
    )


@router.callback_query(F.data == "delete:confirm")
async def delete_confirm(callback: CallbackQuery, context: AppContext) -> None:
    async with context.db.sessions() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        if not user:
            await callback.answer("Данные уже удалены", show_alert=True)
            return
        user_dir = context.settings.storage_dir / user.id
        user.username = None
        user.first_name = None
        user.language_code = None
        consents = list(
            (await session.scalars(select(Consent).where(Consent.user_id == user.id))).all()
        )
        for consent in consents:
            await session.delete(consent)
        await session.commit()
    if context.settings.delete_user_files_on_request and user_dir.exists():
        await asyncio.to_thread(shutil.rmtree, user_dir)
    await callback.answer("Данные удалены", show_alert=True)
    if callback.message:
        await callback.message.answer("Ваши файлы и данные профиля удалены.")


@router.message(Command("balance"))
@router.message(F.text == "💎 Баланс")
@router.message(F.text == "💰 Мой баланс")
@router.callback_query(F.data == "menu:balance")
async def show_balance(event: Message | CallbackQuery, context: AppContext) -> None:
    if not await _feature_enabled(context, "balance"):
        await event.answer("Раздел временно недоступен.")
        return
    telegram_user = event.from_user
    if telegram_user is None:
        return
    async with context.db.sessions() as session:
        user = await get_or_create_user(session, telegram_id=telegram_user.id)
        value = await wallet_balance(session, user.id)
        accesses = await balance(session, user.id)
    text = (
        f"Ваш баланс: <b>{format_rub(value)}</b>.\n\n"
        f"Доступно генераций: <b>{accesses}</b>.\n\n"
        "Активированные доступы сначала используются для стикеров и обработки "
        "фото. Оживление фото оплачивается с рублёвого баланса."
    )
    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            await event.message.answer(text, reply_markup=back_menu())
    else:
        await event.answer(text, reply_markup=back_menu())


@router.message(F.text == "🎟 Активировать доступ")
@router.callback_query(F.data == "access:redeem")
async def start_access_activation(
    event: Message | CallbackQuery,
    state: FSMContext,
) -> None:
    await state.clear()
    await state.set_state(AccessFlow.awaiting_code)
    text = (
        "<b>Активировать доступ</b>\n\n"
        "Скопируйте один код вида <code>YAI-XXXX-XXXX</code> и отправьте его "
        "обычным текстовым сообщением. TXT-файл отправлять не нужно. "
        "После активации доступы к генерации появятся на вашем балансе."
    )
    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            await event.message.answer(text, reply_markup=back_menu())
    else:
        await event.answer(text, reply_markup=back_menu())


@router.message(F.text.startswith("YAI-"))
@router.message(AccessFlow.awaiting_code, F.text)
async def activate_access_code(
    message: Message,
    state: FSMContext,
    context: AppContext,
) -> None:
    telegram_user = message.from_user
    if telegram_user is None:
        return
    async with context.db.sessions() as session:
        user = await get_or_create_user(
            session,
            telegram_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            language_code=telegram_user.language_code,
        )
        try:
            code = await redeem_access_code(
                session,
                user=user,
                raw_code=message.text or "",
            )
        except ValueError as exc:
            errors = {
                "access_code_not_found": "Код не найден. Проверьте написание и попробуйте ещё раз.",
                "access_code_redeemed": "Этот код уже был активирован.",
                "access_code_expired": "Срок действия этого кода истёк.",
                "access_code_disabled": "Этот код отключён. Обратитесь в поддержку.",
            }
            await message.answer(errors.get(str(exc), "Не удалось активировать код."))
            return
        current = await balance(session, user.id)
    await state.clear()
    await message.answer(
        "Доступ активирован ✅\n"
        f"Начислено генераций: <b>{code.accesses}</b>\n"
        f"Теперь доступно: <b>{current}</b>",
        reply_markup=back_menu(),
    )


@router.message(Command("styles"))
@router.message(F.text == "🎨 Сделать стикеры")
@router.callback_query(F.data == "menu:styles")
async def show_sticker_hub(event: Message | CallbackQuery, context: AppContext) -> None:
    if not await _feature_enabled(context, "sticker_creator"):
        await event.answer("Создание стикеров временно недоступно.")
        return
    meme_enabled = setting_enabled(
        await _setting(context, "meme_sticker_enabled", "true")
    )
    if isinstance(event, CallbackQuery):
        await event.answer()
        target = event.message if isinstance(event.message, Message) else None
    else:
        target = event
    if target is None:
        return
    preview = Path("assets/previews/meme-sticker-v1.png")
    caption = (
        "🎨 <b>Стикеры для Telegram</b>\n\n"
        "Выберите обычную коллекцию или создайте мем-стикер со своей точной надписью."
    )
    if await asyncio.to_thread(preview.exists):
        await target.answer_photo(
            FSInputFile(preview),
            caption=caption,
            reply_markup=sticker_hub_menu(meme_enabled=meme_enabled),
        )
    else:
        await target.answer(
            caption,
            reply_markup=sticker_hub_menu(meme_enabled=meme_enabled),
        )


@router.callback_query(F.data == "stickers:classic")
async def show_styles(event: Message | CallbackQuery, context: AppContext) -> None:
    if not await _feature_enabled(context, "sticker_creator"):
        await event.answer("Создание стикеров временно недоступно.")
        return
    async with context.db.sessions() as session:
        templates = list(
            (
                await session.scalars(
                    select(Template)
                    .where(Template.active.is_(True))
                    .order_by(Template.sort_order, Template.title)
                )
            ).all()
        )
        upcoming = list(
            (
                await session.scalars(
                    select(Template)
                    .where(
                        Template.active.is_(False),
                        Template.category == "В разработке",
                    )
                    .order_by(Template.title)
                )
            ).all()
        )
    text = (
        "✨ <b>Выберите коллекцию стикеров</b>\n"
        "В каждом наборе сохраняется ваше лицо, а эмоции и жесты меняются."
    )
    if isinstance(event, CallbackQuery):
        await event.answer()
        target = event.message if isinstance(event.message, Message) else None
    else:
        target = event
    if target is None:
        return
    visible_templates = templates[:4]
    await target.answer_photo(
        BufferedInputFile(
            build_style_grid(visible_templates),
            filename="styles.jpg",
        ),
        caption=text,
        reply_markup=styles_menu(visible_templates),
    )
    if upcoming:
        titles = ", ".join(item.title for item in upcoming)
        await target.answer(f"🚧 В разработке: {titles}.")


@router.callback_query(F.data.startswith("style:"))
async def choose_style(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    slug = (callback.data or "").split(":", 1)[1]
    async with context.db.sessions() as session:
        template = await session.scalar(
            select(Template).where(Template.slug == slug, Template.active.is_(True))
        )
    if not template:
        await callback.answer("Образ больше недоступен", show_alert=True)
        return
    await state.update_data(mode="template", template_slug=slug, prompt=template.prompt)
    await callback.answer()
    if callback.message:
        variants = collection_variants(slug)
        if variants:
            await state.set_state(CreateFlow.awaiting_variant)
            await callback.message.answer(
                f"<b>{template.title}</b>\n{template.description}\n\nВыберите вариант образа:",
                reply_markup=variant_menu(slug, variants),
            )
        else:
            await state.set_state(CreateFlow.awaiting_quantity)
            await callback.message.answer(
                f"<b>{template.title}</b>\n{template.description}\n\nСколько стикеров сделать?",
                reply_markup=quantity_menu(
                    template.slug,
                    prices=await _sticker_prices(context),
                ),
            )


@router.callback_query(CreateFlow.awaiting_variant, F.data.startswith("variant:"))
async def choose_variant(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("Некорректный выбор", show_alert=True)
        return
    slug, variant_key = parts[1], parts[2]
    variant = variant_by_key(slug, variant_key)
    if not variant:
        await callback.answer("Вариант больше недоступен", show_alert=True)
        return
    data = await state.get_data()
    prompt = str(data.get("prompt") or "")
    await state.update_data(
        variant_key=variant.key,
        prompt=f"{prompt}\nSelected collection variant: {variant.prompt}",
    )
    await state.set_state(CreateFlow.awaiting_quantity)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"Выбран образ: <b>{variant.title}</b>\n\nСколько стикеров создать?",
            reply_markup=quantity_menu(
                slug,
                prices=await _sticker_prices(context),
            ),
        )


@router.callback_query(CreateFlow.awaiting_quantity, F.data.startswith("qty:"))
async def choose_quantity(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("Некорректный выбор", show_alert=True)
        return
    slug, raw_quantity = parts[1], parts[2]
    try:
        quantity = int(raw_quantity)
    except ValueError:
        await callback.answer("Некорректное количество", show_alert=True)
        return
    if quantity not in SUPPORTED_STICKER_QUANTITIES:
        await callback.answer("Количество недоступно", show_alert=True)
        return
    async with context.db.sessions() as session:
        template = await session.scalar(
            select(Template).where(Template.slug == slug, Template.active.is_(True))
        )
    if not template:
        await callback.answer("Стиль временно недоступен", show_alert=True)
        return
    await state.update_data(
        quantity=quantity,
        template_slug=template.slug,
    )
    await callback.answer()
    if callback.message:
        prices = await _sticker_prices(context)
        price_text = f" за <b>{prices[quantity]} ₽</b>" if quantity in prices else ""
        if quantity == 1:
            await state.set_state(CreateFlow.awaiting_reaction)
            await callback.message.answer(
                f"Выбран <b>1 стикер</b>{price_text}.\n\nКакую эмоцию или действие сделать?",
                reply_markup=reaction_menu(template.slug),
            )
        else:
            await state.update_data(reaction_key="standard")
            await state.set_state(CreateFlow.awaiting_caption)
            await callback.message.answer(
                f"Выбран набор: <b>{quantity} стикеров</b>{price_text}.\n\n"
                "Эмоции будут подобраны автоматически. Добавить короткие надписи?",
                reply_markup=caption_menu(template.slug),
            )


@router.callback_query(CreateFlow.awaiting_reaction, F.data.startswith("reaction:"))
async def choose_reaction(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("Некорректный выбор", show_alert=True)
        return
    slug, reaction_key = parts[1], parts[2]
    reaction = reaction_by_key(reaction_key)
    await state.update_data(reaction_key=reaction.key)
    await state.set_state(CreateFlow.awaiting_caption)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"Выбрано: {reaction.emoji} <b>{reaction.title}</b>.\n\nДобавить короткую надпись?",
            reply_markup=caption_menu(slug),
        )


@router.callback_query(CreateFlow.awaiting_caption, F.data.startswith("caption:"))
async def choose_caption(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or parts[2] not in {"text", "plain"}:
        await callback.answer("Некорректный выбор", show_alert=True)
        return
    caption_mode = parts[2]
    data = await state.get_data()
    quantity = int(data.get("quantity") or 1)
    reaction_key = str(data.get("reaction_key") or "standard")
    await state.update_data(
        mode=f"sticker:{quantity}:{caption_mode}:{reaction_key}",
        captions_enabled=caption_mode == "text",
    )
    await state.set_state(CreateFlow.awaiting_photo)
    await callback.answer()
    if callback.message:
        captions_text = "с надписями" if caption_mode == "text" else "без надписей"
        await callback.message.answer(
            f"Готовим <b>{quantity} "
            f"{'стикер' if quantity == 1 else 'стикеров'}</b> {captions_text}.\n\n"
            "Отправьте одну чёткую фотографию взрослого человека. "
            "Лучше использовать кадр анфас с хорошо видимым лицом."
        )


async def _show_photo_section(
    event: Message | CallbackQuery,
    context: AppContext,
    *,
    section: str,
) -> None:
    feature_key = "photo_processing" if section == "processing" else "photo_looks"
    if not await _feature_enabled(context, feature_key):
        await event.answer("Раздел временно недоступен.")
        return
    scenarios = scenarios_for_section(section)
    keys = {enabled_setting_key(item.key) for item in scenarios}
    values = await _settings_map(context, keys)
    active = tuple(
        item
        for item in scenarios
        if setting_enabled(values.get(enabled_setting_key(item.key), "true"))
    )
    if not active:
        await event.answer("В этом разделе пока нет доступных функций.")
        return
    prices = {item.key: await _photo_price(context, item.key) for item in active}
    if isinstance(event, CallbackQuery):
        await event.answer()
        target = event.message if isinstance(event.message, Message) else None
    else:
        target = event
    if target is None:
        return
    if section == "processing":
        preview = Path("assets/previews/photo-enhance-before-after-v1.png")
        caption = (
            "✨ <b>Обработка фотографии</b>\n\n"
            "Улучшу исходный кадр или создам профессиональный портрет, сохранив человека."
        )
    else:
        preview = Path("assets/previews/photo-looks-grid-v1.png")
        caption = (
            "👑 <b>Создать фотообраз</b>\n\n"
            "1 — герой кино · 2 — путешествие · 3 — король или королева · "
            "4 — праздничная открытка."
        )
    if await asyncio.to_thread(preview.exists):
        await target.answer_photo(
            FSInputFile(preview),
            caption=caption,
            reply_markup=photo_scenarios_menu(active, prices),
        )
    else:
        await target.answer(caption, reply_markup=photo_scenarios_menu(active, prices))


@router.message(F.text == "✨ Обработать фотографию")
async def show_photo_processing(message: Message, context: AppContext) -> None:
    await _show_photo_section(message, context, section="processing")


@router.message(F.text == "👑 Создать фотообраз")
async def show_photo_looks(message: Message, context: AppContext) -> None:
    await _show_photo_section(message, context, section="looks")


@router.callback_query(F.data.startswith("photo:section:"))
async def show_photo_section_callback(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    section = (callback.data or "").rsplit(":", 1)[1]
    if section not in {"processing", "looks"}:
        await callback.answer("Раздел не найден", show_alert=True)
        return
    await _show_photo_section(callback, context, section=section)


async def _ask_for_photo(message: Message, scenario_title: str, price: Decimal) -> None:
    await message.answer(
        f"Выбрано: <b>{scenario_title}</b> · {format_rub(price)}.\n\n"
        "Отправьте одну чёткую фотографию взрослого человека. "
        "Результат сохранит лицо и исходный ракурс."
    )


@router.callback_query(F.data.startswith("photo:select:"))
async def select_photo_scenario(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    key = (callback.data or "").rsplit(":", 1)[1]
    scenario = scenario_by_key(key)
    if not scenario:
        await callback.answer("Функция не найдена", show_alert=True)
        return
    feature_key = "photo_processing" if scenario.section == "processing" else "photo_looks"
    enabled = setting_enabled(
        await _setting(context, enabled_setting_key(key), "true")
    )
    if not enabled or not await _feature_enabled(context, feature_key):
        await callback.answer("Функция временно выключена", show_alert=True)
        return
    prompt = await _setting(context, prompt_setting_key(key), scenario.prompt)
    await state.update_data(
        photo_scenario=key,
        mode=f"photo:{key}",
        prompt=prompt,
    )
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if scenario.options:
        await state.set_state(PhotoFlow.awaiting_option)
        await callback.message.answer(
            f"<b>{scenario.title}</b>\n{scenario.description}\n\nВыберите вариант:",
            reply_markup=photo_options_menu(scenario),
        )
        return
    await state.set_state(PhotoFlow.awaiting_photo)
    await _ask_for_photo(
        callback.message,
        scenario.title,
        await _photo_price(context, key),
    )


@router.callback_query(PhotoFlow.awaiting_option, F.data.startswith("photo:option:"))
async def select_photo_option(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer("Некорректный выбор", show_alert=True)
        return
    scenario = scenario_by_key(parts[2])
    option = option_by_key(scenario, parts[3]) if scenario else None
    if not scenario or not option:
        await callback.answer("Вариант не найден", show_alert=True)
        return
    data = await state.get_data()
    prompt = f"{data.get('prompt') or scenario.prompt}\nSelected option: {option.prompt}"
    await state.update_data(prompt=prompt, photo_option=option.key)
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if scenario.asks_for_text:
        await state.set_state(PhotoFlow.awaiting_text)
        await callback.message.answer(
            f"Выбрано: <b>{option.title}</b>.\n\n"
            "Напишите точный текст для открытки одним сообщением. "
            "Например: «Алина, с днём рождения! Счастья и любви!» "
            "Используйте текст без эмодзи."
        )
        return
    await state.set_state(PhotoFlow.awaiting_photo)
    await _ask_for_photo(
        callback.message,
        f"{scenario.title} — {option.title}",
        await _photo_price(context, scenario.key),
    )


@router.callback_query(F.data == "stickers:meme")
async def start_meme_sticker(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not setting_enabled(await _setting(context, "meme_sticker_enabled", "true")):
        await callback.answer("Мем-стикер временно выключен", show_alert=True)
        return
    prompt = await _setting(context, "meme_sticker_prompt", MEME_PROMPT)
    await state.set_state(PhotoFlow.awaiting_text)
    await state.update_data(
        photo_scenario="meme",
        mode="sticker:1:text:meme",
        prompt=prompt,
    )
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "😂 <b>Мем-стикер со своим текстом</b>\n\n"
            "Напишите короткую фразу — бот подберёт подходящую эмоцию и нанесёт "
            "ваш текст без ошибок. Например: «Я всё видел»."
        )


@router.message(PhotoFlow.awaiting_text, F.text)
async def receive_photo_text(
    message: Message,
    state: FSMContext,
    context: AppContext,
) -> None:
    text = (message.text or "").strip()
    data = await state.get_data()
    scenario_key = str(data.get("photo_scenario") or "")
    max_length = 80 if scenario_key == "meme" else 180
    if not 2 <= len(text) <= max_length:
        await message.answer(f"Текст должен содержать от 2 до {max_length} символов.")
        return
    allowed_punctuation = set(".,!?—-:;()«»'\"%+№")
    if any(
        not (character.isalnum() or character.isspace() or character in allowed_punctuation)
        for character in text
    ):
        await message.answer(
            "Используйте буквы, цифры и обычные знаки препинания без эмодзи — "
            "так подпись точно отобразится без квадратов."
        )
        return
    prompt = str(data.get("prompt") or "")
    if scenario_key == "meme":
        prompt = f"{prompt}\nThe user's phrase and intended reaction meaning: {text}"
        title = "Мем-стикер"
        price = await _meme_price(context)
    else:
        scenario = scenario_by_key(scenario_key)
        title = scenario.title if scenario else "Открытка"
        price = await _photo_price(context, scenario_key)
    await state.update_data(prompt=attach_local_caption(prompt, text))
    await state.set_state(PhotoFlow.awaiting_photo)
    await _ask_for_photo(message, title, price)


@router.message(PhotoFlow.awaiting_photo, F.photo)
async def receive_scenario_photo(
    message: Message,
    state: FSMContext,
    bot: Bot,
    context: AppContext,
) -> None:
    user = await _user(message, context)
    if not await _has_consent(context, user.id):
        await message.answer("Сначала подтвердите согласие через /start.")
        return
    if not message.photo:
        await message.answer("Отправьте фотографию.")
        return
    photo = message.photo[-1]
    if photo.file_size and photo.file_size > context.settings.max_upload_mb * 1024 * 1024:
        await message.answer(f"Файл больше {context.settings.max_upload_mb} МБ.")
        return
    destination = BytesIO()
    await bot.download(photo.file_id, destination=destination)
    data = await state.get_data()
    scenario_key = str(data.get("photo_scenario") or "")
    mode = str(data.get("mode") or "")
    if scenario_key == "meme":
        price = await _meme_price(context)
    else:
        scenario = scenario_by_key(scenario_key)
        if not scenario:
            await state.clear()
            await message.answer("Сценарий больше недоступен. Выберите его заново.")
            return
        price = await _photo_price(context, scenario_key)
    async with context.db.sessions() as session:
        try:
            generation = await create_generation(
                session,
                context.settings,
                user=user,
                source=destination.getvalue(),
                prompt=str(data.get("prompt") or ""),
                mode=mode,
                quantity=1,
                price_rub=price,
            )
        except ValueError as exc:
            if str(exc) == "insufficient_balance":
                await message.answer(
                    "Недостаточно доступов или средств. Пополните баланс:",
                    reply_markup=await _topup_markup(context),
                )
                return
            raise
    await state.clear()
    result_name = "мем-стикер" if scenario_key == "meme" else "фотография"
    await message.answer(
        f"Фото принято ✅\nЗадание <code>{generation.id[:8]}</code> поставлено в очередь.\n"
        f"Будет создана: <b>{result_name}</b>.\n"
        f"Списано: <b>{_generation_charge_text(generation)}</b>."
    )


@router.message(Command("create"))
@router.message(F.text == "✨ Создать по описанию")
@router.callback_query(F.data == "menu:create")
async def custom_create(
    event: Message | CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not await _feature_enabled(context, "custom_create"):
        await event.answer("Функция пока в разработке.")
        return
    await state.set_state(CreateFlow.awaiting_prompt)
    text = (
        "Опишите будущий кадр: одежду, фон, свет, ракурс и настроение. "
        "Внешность описывать не нужно — она берётся с фотографии."
    )
    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            await event.message.answer(text)
    else:
        await event.answer(text)


@router.message(Command("edit"))
@router.message(F.text == "✏️ Редактировать фото")
@router.callback_query(F.data == "menu:edit")
async def edit_create(
    event: Message | CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not await _feature_enabled(context, "photo_edit"):
        await event.answer("Функция пока в разработке.")
        return
    await state.set_state(CreateFlow.awaiting_prompt)
    await state.update_data(mode="edit")
    text = "Опишите, что именно нужно изменить на фотографии, а что обязательно сохранить."
    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            await event.message.answer(text)
    else:
        await event.answer(text)


@router.message(CreateFlow.awaiting_prompt, F.text)
async def receive_prompt(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    mode = str(data.get("mode") or "custom")
    prompt = message.text.strip() if message.text else ""
    if len(prompt) < 15:
        await message.answer("Описание слишком короткое. Добавьте фон, свет и детали кадра.")
        return
    if mode == "edit":
        prompt = (
            "Edit the uploaded photo according to the request while preserving the person's "
            "recognizable identity, realistic anatomy and all unspecified details. Request: "
            + prompt
        )
    else:
        prompt = (
            "Create a photorealistic portrait using the uploaded person as identity reference. "
            "Preserve recognizable facial identity, natural skin and realistic anatomy. "
            "No text, watermark or logos. User request: " + prompt
        )
    await state.update_data(mode=mode, prompt=prompt)
    await state.set_state(CreateFlow.awaiting_photo)
    await message.answer("Теперь отправьте одну фотографию.")


@router.message(CreateFlow.awaiting_photo, F.photo)
async def receive_photo(
    message: Message,
    state: FSMContext,
    bot: Bot,
    context: AppContext,
) -> None:
    user = await _user(message, context)
    if not await _has_consent(context, user.id):
        await message.answer("Сначала подтвердите согласие через /start.")
        return
    if not message.photo:
        await message.answer("Отправьте фотографию.")
        return
    photo = message.photo[-1]
    if photo.file_size and photo.file_size > context.settings.max_upload_mb * 1024 * 1024:
        await message.answer(f"Файл больше {context.settings.max_upload_mb} МБ.")
        return
    destination = BytesIO()
    await bot.download(photo.file_id, destination=destination)
    data = await state.get_data()
    template = None
    async with context.db.sessions() as session:
        if slug := data.get("template_slug"):
            template = await session.scalar(select(Template).where(Template.slug == slug))
        quantity = int(data.get("quantity") or 1)
        selected_mode = str(data.get("mode") or "custom")
        generation_price = Decimal("0")
        if selected_mode.startswith("sticker:"):
            package = await session.scalar(
                select(Package).where(
                    Package.credits == quantity,
                    Package.active.is_(True),
                )
            )
            if not package:
                await message.answer("Цена этого набора временно не настроена.")
                return
            generation_price = await package_price(session, package)
        try:
            generation = await create_generation(
                session,
                context.settings,
                user=user,
                source=destination.getvalue(),
                prompt=str(data.get("prompt") or ""),
                mode=selected_mode,
                template=template,
                quantity=quantity,
                price_rub=generation_price,
            )
        except ValueError as exc:
            if str(exc) == "insufficient_balance":
                await message.answer(
                    "Недостаточно доступов или средств. Пополните баланс:",
                    reply_markup=await _topup_markup(context),
                )
                return
            raise
    await state.clear()
    await message.answer(
        f"Фото принято ✅\nЗадание <code>{generation.id[:8]}</code> поставлено в очередь.\n"
        f"Будет создано стикеров: <b>{quantity}</b>.\n"
        f"Списано: <b>{_generation_charge_text(generation)}</b>."
    )


async def _packages_markup(context: AppContext) -> InlineKeyboardMarkup:
    async with context.db.sessions() as session:
        packages = list(
            (
                await session.scalars(
                    select(Package)
                    .where(Package.active.is_(True))
                    .order_by(Package.sort_order, Package.amount_rub)
                )
            ).all()
        )
    return packages_menu(packages)


async def _topup_markup(context: AppContext) -> InlineKeyboardMarkup:
    configured_amounts = parse_amount_list(
        await _setting(context, "topup_amounts_rub", "99,500,1000,2000,5000")
    )
    options: list[tuple[str, Decimal]] = []
    used_amounts: set[Decimal] = set()
    async with context.db.sessions() as session:
        packages = list(
            (
                await session.scalars(
                    select(Package)
                    .where(Package.active.is_(True))
                    .order_by(Package.sort_order)
                )
            ).all()
        )
        for package in packages:
            amount = await package_price(session, package)
            options.append(
                (
                    f"{package.credits} стик. — {format_rub(amount)}",
                    amount,
                )
            )
            used_amounts.add(amount)
        video_feature = await session.get(FeatureFlag, "video_animation")
        if video_feature and video_feature.enabled:
            video_price = parse_money(await get_setting(session, "video_price_rub", "200"))
            options.append((f"Видео — {format_rub(video_price)}", video_price))
            used_amounts.add(video_price)
    if await _feature_enabled(context, "photo_processing") and setting_enabled(
        await _setting(context, enabled_setting_key("enhance"), "true")
    ):
        photo_price = await _photo_price(context, "enhance")
        options.append((f"Обработка фото — {format_rub(photo_price)}", photo_price))
        used_amounts.add(photo_price)
    if await _feature_enabled(context, "photo_looks") and setting_enabled(
        await _setting(context, enabled_setting_key("movie"), "true")
    ):
        look_price = await _photo_price(context, "movie")
        options.append((f"Фотообраз — {format_rub(look_price)}", look_price))
        used_amounts.add(look_price)
    if setting_enabled(await _setting(context, "meme_sticker_enabled", "true")):
        meme_price = await _meme_price(context)
        options.append((f"Мем-стикер — {format_rub(meme_price)}", meme_price))
        used_amounts.add(meme_price)
    for amount in configured_amounts:
        if amount not in used_amounts:
            options.append((f"На баланс — {format_rub(amount)}", amount))
            used_amounts.add(amount)
    custom_enabled = setting_enabled(
        await _setting(context, "custom_topup_enabled", "true"),
        default=True,
    )
    return topup_amounts_menu(options, custom_enabled=custom_enabled)


async def _payment_flags(context: AppContext) -> tuple[bool, bool]:
    manual = setting_enabled(
        await _setting(context, "manual_payments_enabled", "true"),
        default=True,
    )
    cloud = setting_enabled(
        await _setting(context, "cloudpayments_enabled", "false"),
        default=False,
    )
    cloud = cloud and context.settings.payment_provider == "cloudpayments"
    return manual, cloud


@router.message(Command("buy"))
@router.message(F.text == "💳 Купить генерации")
@router.message(F.text == "🛍 Купить стикеры")
@router.message(F.text == "💳 Пополнить баланс")
@router.message(F.text == "🛒 Купить доступ к генерации")
@router.callback_query(F.data == "menu:buy")
async def buy(event: Message | CallbackQuery, context: AppContext) -> None:
    if not await _feature_enabled(context, "payments"):
        await event.answer("Пополнение баланса временно недоступно.")
        return
    markup = await _topup_markup(context)
    text = (
        "Выберите сумму пополнения для покупки генераций.\n"
        "Оплата конкретной генерации списывается с общего рублёвого баланса."
    )
    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            await event.message.answer(text, reply_markup=markup)
    else:
        await event.answer(text, reply_markup=markup)


async def _show_payment_methods(
    event: Message | CallbackQuery,
    context: AppContext,
    amount: Decimal,
) -> None:
    manual, cloud = await _payment_flags(context)
    if not manual and not cloud:
        await event.answer("Пополнение временно недоступно.")
        return
    markup = payment_methods_menu(
        amount,
        manual_enabled=manual,
        cloudpayments_enabled=cloud,
    )
    text = f"Сумма пополнения: <b>{format_rub(amount)}</b>.\nВыберите способ оплаты:"
    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            await event.message.answer(text, reply_markup=markup)
    else:
        await event.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("topup:amount:"))
async def choose_topup_amount(callback: CallbackQuery, context: AppContext) -> None:
    try:
        amount = parse_money((callback.data or "").rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректная сумма", show_alert=True)
        return
    await _show_payment_methods(callback, context, amount)


@router.callback_query(F.data == "topup:custom")
async def request_custom_topup(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not setting_enabled(
        await _setting(context, "custom_topup_enabled", "true"),
        default=True,
    ):
        await callback.answer("Произвольная сумма отключена", show_alert=True)
        return
    minimum = parse_money(await _setting(context, "custom_topup_min_rub", "99"))
    maximum = parse_money(await _setting(context, "custom_topup_max_rub", "100000"))
    await state.set_state(PaymentFlow.awaiting_custom_amount)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Введите сумму пополнения одним сообщением.\n"
            f"Допустимо: от {format_rub(minimum)} до {format_rub(maximum)}."
        )


@router.message(PaymentFlow.awaiting_custom_amount, F.text)
async def receive_custom_topup(message: Message, state: FSMContext, context: AppContext) -> None:
    try:
        amount = parse_money(message.text or "")
        minimum = parse_money(await _setting(context, "custom_topup_min_rub", "99"))
        maximum = parse_money(await _setting(context, "custom_topup_max_rub", "100000"))
    except ValueError:
        await message.answer("Введите сумму числом, например: 500")
        return
    if not minimum <= amount <= maximum:
        await message.answer(
            f"Допустимо: от {format_rub(minimum)} до {format_rub(maximum)}."
        )
        return
    await state.clear()
    await _show_payment_methods(message, context, amount)


@router.callback_query(F.data.startswith("topup:method:"))
async def choose_payment_method(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer("Некорректный выбор", show_alert=True)
        return
    provider_name = parts[2]
    try:
        amount = parse_money(parts[3])
    except ValueError:
        await callback.answer("Некорректная сумма", show_alert=True)
        return
    manual_enabled, cloud_enabled = await _payment_flags(context)
    if provider_name == "manual" and not manual_enabled:
        await callback.answer("Ручное пополнение отключено", show_alert=True)
        return
    if provider_name == "cloudpayments" and not cloud_enabled:
        await callback.answer("Оплата картой пока недоступна", show_alert=True)
        return

    async with context.db.sessions() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
        payment, checkout = await create_topup_payment(
            session,
            context.payment_provider if provider_name == "cloudpayments" else None,
            user=user,
            amount_rub=amount,
            provider_name=provider_name,
        )
    await callback.answer()
    if not callback.message:
        return
    if provider_name == "cloudpayments" and checkout:
        await callback.message.answer(
            f"Пополнение на <b>{format_rub(amount)}</b>.",
            reply_markup=payment_menu(checkout.url, payment.id),
        )
        return

    instructions = await _setting(
        context,
        "manual_payment_instructions",
        "Оплатите выбранную сумму, затем нажмите «Я оплатил» и отправьте чек.",
    )
    payment_url = await _setting(context, "manual_payment_url", "")
    qr_path = Path(await _setting(context, "manual_payment_qr_path", ""))
    caption = (
        f"<b>Ручное пополнение на {format_rub(amount)}</b>\n"
        f"Номер заявки: <code>{payment.id[:8]}</code>\n\n{escape(instructions)}"
    )
    markup = manual_payment_menu(payment.id, payment_url)
    qr_exists = bool(str(qr_path)) and await asyncio.to_thread(qr_path.is_file)
    if qr_exists:
        await callback.message.answer_photo(
            FSInputFile(qr_path),
            caption=caption,
            reply_markup=markup,
        )
    else:
        await callback.message.answer(caption, reply_markup=markup)


@router.callback_query(F.data.startswith("manual:paid:"))
async def request_manual_proof(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    payment_id = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        payment = await session.get(Payment, payment_id)
        user = (
            await session.scalar(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
        )
    if (
        not payment
        or not user
        or payment.user_id != user.id
        or payment.provider != "manual"
        or payment.status not in {PaymentStatus.PENDING.value, PaymentStatus.CREATED.value}
    ):
        await callback.answer("Заявка недоступна", show_alert=True)
        return
    await state.set_state(PaymentFlow.awaiting_proof)
    await state.update_data(manual_payment_id=payment.id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Отправьте одним сообщением фотографию или файл с чеком."
        )


@router.message(PaymentFlow.awaiting_proof, F.photo | F.document)
async def receive_manual_proof(
    message: Message,
    state: FSMContext,
    context: AppContext,
    bot: Bot,
) -> None:
    data = await state.get_data()
    payment_id = str(data.get("manual_payment_id") or "")
    file_id = ""
    file_type = ""
    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
    elif message.document:
        file_id = message.document.file_id
        file_type = "document"
    if not file_id:
        await message.answer("Пришлите фотографию или файл с чеком.")
        return
    async with context.db.sessions() as session:
        payment = await session.get(Payment, payment_id)
        user = (
            await session.scalar(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            if message.from_user
            else None
        )
        if not payment or not user or payment.user_id != user.id:
            await state.clear()
            await message.answer("Заявка не найдена.")
            return
        payment.proof_file_id = file_id
        payment.proof_file_type = file_type
        payment.status = PaymentStatus.SUBMITTED.value
        payment.submitted_at = datetime.now(UTC)
        await session.commit()
    await state.clear()
    await message.answer(
        "Чек отправлен администратору ✅\n"
        f"Заявка: <code>{payment.id[:8]}</code>. Баланс появится после проверки."
    )
    admin_text = (
        "<b>Новая заявка на ручное пополнение</b>\n"
        f"Заявка: <code>{payment.id[:8]}</code>\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n"
        f"Username: @{escape(user.username or '—')}\n"
        f"Сумма: <b>{format_rub(payment.amount)}</b>"
    )
    for admin_id in context.settings.admin_ids:
        try:
            if file_type == "photo":
                await bot.send_photo(
                    admin_id,
                    file_id,
                    caption=admin_text,
                    reply_markup=admin_manual_payment_menu(payment.id),
                )
            else:
                await bot.send_document(
                    admin_id,
                    file_id,
                    caption=admin_text,
                    reply_markup=admin_manual_payment_menu(payment.id),
                )
        except Exception:
            continue


@router.callback_query(F.data.startswith("buy:"))
async def buy_package(callback: CallbackQuery, context: AppContext) -> None:
    code = (callback.data or "").split(":", 1)[1]
    async with context.db.sessions() as session:
        user = await get_or_create_user(session, telegram_id=callback.from_user.id)
        package = await session.scalar(
            select(Package).where(Package.code == code, Package.active.is_(True))
        )
        if not package:
            await callback.answer("Пакет недоступен", show_alert=True)
            return
        payment, checkout = await create_payment(
            session,
            context.payment_provider,
            user=user,
            package=package,
            provider_name=context.settings.payment_provider,
        )
    await callback.answer()
    if callback.message:
        markup = (
            mock_payment_menu(payment.id)
            if context.settings.payment_provider == "mock"
            else payment_menu(checkout.url, payment.id)
        )
        await callback.message.answer(
            f"{package.title}: {package.credits} стикеров за {package.amount_rub:.0f} ₽",
            reply_markup=markup,
        )


@router.callback_query(F.data.startswith("mockpay:"))
async def mock_pay_callback(callback: CallbackQuery, context: AppContext) -> None:
    if context.settings.payment_provider != "mock":
        await callback.answer("Тестовая оплата отключена", show_alert=True)
        return
    payment_id = (callback.data or "").split(":", 1)[1]
    try:
        async with context.db.sessions() as session:
            payment, credited = await mark_payment_paid(
                session,
                payment_id=payment_id,
                transaction_id=f"mock-telegram-{payment_id}",
                account_id=str(callback.from_user.id),
                credit_validity_days=context.settings.credit_validity_days,
            )
    except (LookupError, ValueError):
        await callback.answer("Не удалось подтвердить оплату", show_alert=True)
        return
    await callback.answer("Оплата подтверждена", show_alert=True)
    if callback.message:
        status = "начислены" if credited else "уже были начислены"
        await callback.message.answer(
            "Тестовая оплата подтверждена ✅\n"
            f"{format_rub(payment.amount)} {status} на баланс.",
            reply_markup=await _main_menu(context),
        )


@router.callback_query(F.data.startswith("payment:check:"))
async def check_payment(callback: CallbackQuery, context: AppContext) -> None:
    payment_id = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        payment = await session.get(Payment, payment_id)
    if payment and payment.status == "paid":
        await callback.answer("Оплата подтверждена ✅", show_alert=True)
    else:
        await callback.answer("Оплата пока не подтверждена", show_alert=True)


@router.message(Command("orders"))
@router.message(F.text == "🖼 Мои стикеры")
@router.message(F.text == "🖼 Мои работы")
@router.callback_query(F.data == "menu:orders")
async def orders(event: Message | CallbackQuery, context: AppContext) -> None:
    if not await _feature_enabled(context, "orders"):
        await event.answer("История временно недоступна.")
        return
    if event.from_user is None:
        return
    async with context.db.sessions() as session:
        user = await get_or_create_user(session, telegram_id=event.from_user.id)
        generations = list(
            (
                await session.scalars(
                    select(Generation)
                    .where(Generation.user_id == user.id)
                    .order_by(Generation.created_at.desc())
                    .limit(10)
                )
            ).all()
        )
    text = "Последние генерации:\n" + (
        "\n".join(f"• {item.id[:8]} — {item.status}" for item in generations)
        if generations
        else "Пока нет генераций."
    )
    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            await event.message.answer(text, reply_markup=back_menu())
    else:
        await event.answer(text, reply_markup=back_menu())


@router.message(Command("support"))
@router.message(F.text == "🛟 Написать в поддержку")
@router.callback_query(F.data == "menu:support")
async def support(
    event: Message | CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    await _begin_support(event, state, context)


@router.message(SupportFlow.awaiting_message, F.text)
async def support_message(
    message: Message,
    state: FSMContext,
    context: AppContext,
    bot: Bot,
) -> None:
    user = await _user(message, context)
    state_data = await state.get_data()
    async with context.db.sessions() as session:
        ticket = await create_ticket(
            session,
            user=user,
            category=str(state_data.get("category") or "other"),
            message=message.text or "",
        )
    await state.clear()
    await message.answer(
        f"Обращение <code>{ticket.id[:8]}</code> создано. Ответ придёт сюда, в чат с ботом."
    )
    destinations = (
        {context.settings.support_chat_id}
        if context.settings.support_chat_id
        else set(context.settings.admin_ids)
    )
    for destination in destinations:
        await bot.send_message(
            destination,
            f"🛟 Новое обращение <code>{ticket.id}</code>\n"
            f"Пользователь: <code>{user.telegram_id}</code>\n\n"
            f"{escape(ticket.message)}",
            reply_markup=admin_ticket_menu(ticket),
        )


@router.callback_query(F.data == "menu:main")
async def callback_main(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Главное меню:",
            reply_markup=await _main_menu(context),
        )
        await callback.message.answer(
            "Что хотите сделать?",
            reply_markup=await _home_actions_menu(context),
        )


async def _send_generation_admin(message: Message, context: AppContext) -> None:
    async with context.db.sessions() as session:
        users_count = await session.scalar(select(func.count(User.id)))
        payments_count = await session.scalar(select(func.count(Payment.id)))
        generations_count = await session.scalar(select(func.count(Generation.id)))
    await message.answer(
        "<b>Администрирование</b>\n"
        f"Пользователей: {users_count}\n"
        f"Платежей: {payments_count}\n"
        f"Генераций: {generations_count}\n\n"
        "Все основные настройки доступны кнопками ниже.",
        reply_markup=admin_menu(),
    )


@router.message(Command("animate"))
@router.message(F.text == "🎬 Оживить фотографию")
@router.callback_query(F.data == "video:start")
async def start_video_generation(
    event: Message | CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not await _feature_enabled(context, "video_animation"):
        await event.answer("Оживление фотографий временно недоступно.")
        return
    duration = int(await _setting(context, "video_duration_seconds", "5"))
    price = parse_money(await _setting(context, "video_price_rub", "200"))
    title = await _setting(context, "video_title", "Оживить фотографию")
    description = await _setting(
        context,
        "video_description",
        "Создам короткое вертикальное видео, сохранив лица и одежду.",
    )
    await state.clear()
    await state.set_state(VideoFlow.awaiting_photo)
    text = (
        f"<b>{escape(title)}</b> · {format_rub(price)}\n"
        f"{escape(description)}\n\n"
        "Отправьте одну фотографию. На ней может быть один или несколько человек.\n\n"
        f"Создам вертикальное видео примерно на "
        f"{duration} секунд. Лица, одежда и количество "
        "людей должны сохраниться."
    )
    if isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            await event.message.answer(text)
    else:
        await event.answer(text)


@router.message(VideoFlow.awaiting_photo, F.photo)
async def receive_video_photo(
    message: Message,
    state: FSMContext,
    bot: Bot,
    context: AppContext,
) -> None:
    if not message.photo:
        await message.answer("Отправьте фотографию.")
        return
    photo = message.photo[-1]
    if photo.file_size and photo.file_size > context.settings.max_upload_mb * 1024 * 1024:
        await message.answer(f"Файл больше {context.settings.max_upload_mb} МБ.")
        return
    destination = BytesIO()
    await bot.download(photo.file_id, destination=destination)
    user = await _user(message, context)
    if not await _has_consent(context, user.id):
        await state.clear()
        await message.answer("Сначала подтвердите согласие через /start.")
        return
    prompt = await _setting(context, "video_prompt", "")
    duration = int(await _setting(context, "video_duration_seconds", "5"))
    price = parse_money(await _setting(context, "video_price_rub", "200"))
    async with context.db.sessions() as session:
        try:
            generation = await create_generation(
                session,
                context.settings,
                user=user,
                source=destination.getvalue(),
                prompt=prompt,
                mode=f"video:{duration}",
                quantity=1,
                price_rub=price,
            )
        except ValueError as exc:
            if str(exc) == "insufficient_balance":
                await message.answer(
                    "Недостаточно доступов или средств. Пополните баланс:",
                    reply_markup=await _topup_markup(context),
                )
                return
            raise
    await state.clear()
    await message.answer(
        "Фото принято ✅\n"
        f"Видеозадание <code>{generation.id[:8]}</code> поставлено в очередь.\n"
        f"Списано: <b>{_generation_charge_text(generation)}</b>.\n"
        "Создание может занять несколько минут. Готовое MP4 придёт сюда автоматически."
    )


async def _admin_callback_allowed(
    callback: CallbackQuery,
    context: AppContext,
) -> bool:
    if callback.from_user.id in context.settings.admin_ids:
        return True
    await callback.answer("Недостаточно прав", show_alert=True)
    return False


@router.callback_query(F.data == "admin:main")
async def admin_callback_main(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    await callback.answer()
    if callback.message:
        await callback.message.answer("<b>Админ-панель</b>", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:access_codes")
async def admin_access_codes(callback: CallbackQuery, context: AppContext) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    async with context.db.sessions() as session:
        stats = await access_code_stats(session)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "<b>Доступы и коды</b>\n\n"
            f"Всего создано: <b>{stats.total}</b>\n"
            f"Осталось: <b>{stats.active}</b>\n"
            f"Использовано: <b>{stats.redeemed}</b>\n"
            f"Истёкло: <b>{stats.expired}</b>\n"
            f"Отключено: <b>{stats.disabled}</b>",
            reply_markup=access_code_admin_menu(),
        )


@router.callback_query(F.data == "admin:access_codes:create")
async def admin_start_access_code_batch(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    await state.clear()
    await state.set_state(AdminAccessCodeFlow.awaiting_count)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Сколько одноразовых кодов создать?\n"
            "Отправьте целое число от 1 до 500."
        )


@router.message(AdminAccessCodeFlow.awaiting_count, F.text)
async def admin_access_code_count(message: Message, state: FSMContext, context: AppContext) -> None:
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        return
    try:
        count = int((message.text or "").strip())
    except ValueError:
        await message.answer("Нужно отправить целое число от 1 до 500.")
        return
    if not 1 <= count <= 500:
        await message.answer("Допустимо от 1 до 500 кодов в одной партии.")
        return
    await state.update_data(access_code_count=count)
    await state.set_state(AdminAccessCodeFlow.awaiting_accesses)
    await message.answer(
        "Сколько генераций должен начислять <b>каждый</b> код?\n"
        "Например: <code>1</code>, <code>5</code> или <code>10</code>."
    )


@router.message(AdminAccessCodeFlow.awaiting_accesses, F.text)
async def admin_access_code_accesses(
    message: Message,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        return
    try:
        accesses = int((message.text or "").strip())
    except ValueError:
        await message.answer("Нужно отправить целое число.")
        return
    if not 1 <= accesses <= 1000:
        await message.answer("Допустимо от 1 до 1000 генераций на один код.")
        return
    await state.update_data(accesses_per_code=accesses)
    await message.answer(
        "Выберите срок действия кодов:",
        reply_markup=access_code_expiry_menu(),
    )


@router.callback_query(F.data.startswith("admin:access_codes:expiry:"))
async def admin_create_access_code_batch(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    data = await state.get_data()
    count = int(data.get("access_code_count") or 0)
    accesses = int(data.get("accesses_per_code") or 0)
    if not count or not accesses:
        await callback.answer("Начните создание партии заново", show_alert=True)
        await state.clear()
        return
    raw_expiry = (callback.data or "").rsplit(":", 1)[1]
    expires_in_days = None if raw_expiry == "none" else int(raw_expiry)
    async with context.db.sessions() as session:
        batch, codes = await create_access_code_batch(
            session,
            count=count,
            accesses_per_code=accesses,
            created_by=callback.from_user.id,
            expires_in_days=expires_in_days,
        )
        session.add(
            AuditLog(
                actor_telegram_id=callback.from_user.id,
                action="access_code_batch_created",
                target_type="access_code_batch",
                target_id=batch.id,
                details=f"count={count}; accesses={accesses}; expiry={raw_expiry}",
            )
        )
        await session.commit()
    await state.clear()
    await callback.answer("Коды созданы", show_alert=True)
    if callback.message:
        expiry_text = (
            f"{expires_in_days} дней" if expires_in_days is not None else "без срока"
        )
        await callback.message.answer(
            "Партия создана ✅\n"
            f"Кодов: <b>{count}</b>\n"
            f"Генераций по каждому коду: <b>{accesses}</b>\n"
            f"Срок: <b>{expiry_text}</b>"
        )
        if count <= 10:
            visible_codes = "\n".join(f"<code>{escape(code.code)}</code>" for code in codes)
            await callback.message.answer(
                "Скопируйте нужный код нажатием на строку:\n\n" + visible_codes
            )
        content = "\n".join(code.code for code in codes).encode("utf-8")
        await callback.message.answer_document(
            BufferedInputFile(content, filename=f"access-codes-{batch.id[:8]}.txt"),
            caption="Коды партии. Сохраните файл в безопасном месте.",
            reply_markup=access_code_admin_menu(),
        )


@router.callback_query(F.data.startswith("admin:access_codes:list:"))
async def admin_list_access_codes(callback: CallbackQuery, context: AppContext) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    status = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        codes = await recent_access_codes(session, status=status, limit=20)
    await callback.answer()
    if not callback.message:
        return
    if not codes:
        await callback.message.answer(
            "В этом списке пока нет кодов.",
            reply_markup=access_code_admin_menu(),
        )
        return
    title = "Оставшиеся коды" if status == "active" else "Использованные коды"
    lines = [f"<b>{title}</b> (последние 20)", ""]
    for code in codes:
        details = (
            f" · Telegram ID <code>{code.redeemed_by_telegram_id}</code>"
            if code.redeemed_by_telegram_id
            else ""
        )
        lines.append(
            f"<code>{code.code}</code> · {code.accesses} ген.{details}"
        )
    await callback.message.answer(
        "\n".join(lines),
        reply_markup=access_code_admin_menu(),
    )


@router.callback_query(F.data == "admin:access_codes:excel")
async def admin_export_access_codes(callback: CallbackQuery, context: AppContext) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    async with context.db.sessions() as session:
        stats = await access_code_stats(session)
        rows = await access_code_report_rows(session)
    report = await asyncio.to_thread(build_access_codes_workbook, rows, stats)
    await callback.answer()
    if callback.message:
        filename = f"access-codes-{datetime.now(UTC):%Y-%m-%d-%H%M}.xlsx"
        await callback.message.answer_document(
            BufferedInputFile(report, filename=filename),
            caption=(
                f"Отчёт готов: осталось {stats.active}, "
                f"использовано {stats.redeemed}."
            ),
            reply_markup=access_code_admin_menu(),
        )


@router.callback_query(F.data == "admin:video")
async def admin_video_settings(callback: CallbackQuery, context: AppContext) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    price = parse_money(await _setting(context, "video_price_rub", "200"))
    duration = await _setting(context, "video_duration_seconds", "5")
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "<b>Настройки видео</b>\n"
            f"Цена: {format_rub(price)}\n"
            f"Длительность: {escape(duration)} сек.\n"
            f"Модель сервера: <code>{escape(context.settings.video_model)}</code>",
            reply_markup=admin_video_menu(),
        )


@router.callback_query(F.data == "admin:payments")
async def admin_payment_settings(callback: CallbackQuery, context: AppContext) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    manual = setting_enabled(
        await _setting(context, "manual_payments_enabled", "true"),
        default=True,
    )
    cloud = setting_enabled(
        await _setting(context, "cloudpayments_enabled", "false"),
        default=False,
    )
    custom_topup = setting_enabled(
        await _setting(context, "custom_topup_enabled", "true"),
        default=True,
    )
    await callback.answer()
    if callback.message:
        cloud_note = (
            "настроен"
            if context.settings.payment_provider == "cloudpayments"
            else "не настроен в переменных сервера"
        )
        await callback.message.answer(
            "<b>Способы оплаты</b>\n"
            f"CloudPayments: {cloud_note}.\n"
            "Ручной способ можно отключить после запуска эквайринга.",
            reply_markup=admin_payments_menu(
                manual_enabled=manual,
                cloudpayments_enabled=cloud,
                custom_topup_enabled=custom_topup,
            ),
        )


@router.callback_query(F.data.startswith("admin:payment_toggle:"))
async def admin_toggle_payment_method(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    key = (callback.data or "").rsplit(":", 1)[1]
    if key not in {
        "manual_payments_enabled",
        "cloudpayments_enabled",
        "custom_topup_enabled",
    }:
        await callback.answer("Настройка не найдена", show_alert=True)
        return
    if key == "cloudpayments_enabled" and context.settings.payment_provider != "cloudpayments":
        await callback.answer(
            "Сначала добавьте ключи CloudPayments в переменные сервера",
            show_alert=True,
        )
        return
    async with context.db.sessions() as session:
        setting = await session.get(BotSetting, key)
        if not setting:
            await callback.answer("Настройка не найдена", show_alert=True)
            return
        setting.value = (
            "false" if setting_enabled(setting.value, default=False) else "true"
        )
        await session.commit()
        manual = setting_enabled(
            await _setting(context, "manual_payments_enabled", "true"),
            default=True,
        )
        cloud = setting_enabled(
            await _setting(context, "cloudpayments_enabled", "false"),
            default=False,
        )
        custom_topup = setting_enabled(
            await _setting(context, "custom_topup_enabled", "true"),
            default=True,
        )
    await callback.answer("Настройка сохранена")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(
            reply_markup=admin_payments_menu(
                manual_enabled=manual,
                cloudpayments_enabled=cloud,
                custom_topup_enabled=custom_topup,
            )
        )


@router.callback_query(F.data == "admin:payment_qr")
async def admin_request_payment_qr(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    await state.set_state(AdminFlow.awaiting_payment_qr)
    await callback.answer()
    if callback.message:
        await callback.message.answer("Отправьте новое изображение QR-кода.")


@router.message(AdminFlow.awaiting_payment_qr, F.photo)
async def admin_save_payment_qr(
    message: Message,
    state: FSMContext,
    context: AppContext,
    bot: Bot,
) -> None:
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        return
    if not message.photo:
        await message.answer("Отправьте изображение.")
        return
    destination = BytesIO()
    await bot.download(message.photo[-1].file_id, destination=destination)
    qr_dir = context.settings.storage_dir / "admin_payments"
    await asyncio.to_thread(qr_dir.mkdir, parents=True, exist_ok=True)
    qr_path = qr_dir / "payment-qr.jpg"
    await asyncio.to_thread(qr_path.write_bytes, destination.getvalue())
    async with context.db.sessions() as session:
        setting = await session.get(BotSetting, "manual_payment_qr_path")
        if setting:
            setting.value = str(qr_path)
        await session.commit()
    await state.clear()
    await message.answer("QR-код сохранён ✅", reply_markup=admin_menu())


async def _send_pending_payments(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    async with context.db.sessions() as session:
        payments = list(
            (
                await session.scalars(
                    select(Payment)
                    .where(
                        Payment.provider == "manual",
                        Payment.status == PaymentStatus.SUBMITTED.value,
                    )
                    .order_by(Payment.submitted_at)
                    .limit(20)
                )
            ).all()
        )
        users = {
            payment.user_id: await session.get(User, payment.user_id)
            for payment in payments
        }
    await callback.answer()
    if not callback.message:
        return
    if not payments:
        await callback.message.answer("Новых заявок на оплату нет.")
        return
    for payment in payments:
        user = users.get(payment.user_id)
        text = (
            f"Заявка <code>{payment.id[:8]}</code>\n"
            f"Сумма: <b>{format_rub(payment.amount)}</b>\n"
            f"Telegram ID: <code>{user.telegram_id if user else '—'}</code>"
        )
        await callback.message.answer(
            text,
            reply_markup=admin_manual_payment_menu(payment.id),
        )


@router.callback_query(F.data == "admin:payments_pending")
async def admin_pending_payments(callback: CallbackQuery, context: AppContext) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    await _send_pending_payments(callback, context)


@router.callback_query(F.data.startswith("admin:payment:approve:"))
async def admin_approve_payment(
    callback: CallbackQuery,
    context: AppContext,
    bot: Bot,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    payment_id = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        payment = await session.get(Payment, payment_id)
        if (
            not payment
            or payment.provider != "manual"
            or payment.status
            not in {PaymentStatus.SUBMITTED.value, PaymentStatus.PAID.value}
        ):
            await callback.answer("Заявка уже обработана или не найдена", show_alert=True)
            return
        payment, credited = await mark_payment_paid(
            session,
            payment_id=payment.id,
            transaction_id=f"manual-{payment.id}",
            credit_validity_days=context.settings.credit_validity_days,
        )
        payment.reviewed_at = datetime.now(UTC)
        payment.reviewed_by = callback.from_user.id
        user = await session.get(User, payment.user_id)
        session.add(
            AuditLog(
                actor_telegram_id=callback.from_user.id,
                action="manual_payment_approved",
                target_type="payment",
                target_id=payment.id,
                details=f"amount={payment.amount}",
            )
        )
        await session.commit()
        current_balance = await wallet_balance(session, payment.user_id)
    await callback.answer("Платёж подтверждён", show_alert=True)
    if user and credited:
        await bot.send_message(
            user.telegram_id,
            "Пополнение подтверждено ✅\n"
            f"Начислено: <b>{format_rub(payment.amount)}</b>\n"
            f"Баланс: <b>{format_rub(current_balance)}</b>",
        )


@router.callback_query(F.data.startswith("admin:payment:reject:"))
async def admin_reject_payment(
    callback: CallbackQuery,
    context: AppContext,
    bot: Bot,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    payment_id = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        payment = await session.get(Payment, payment_id)
        if not payment or payment.status != PaymentStatus.SUBMITTED.value:
            await callback.answer("Заявка уже обработана или не найдена", show_alert=True)
            return
        payment.status = PaymentStatus.REJECTED.value
        payment.reviewed_at = datetime.now(UTC)
        payment.reviewed_by = callback.from_user.id
        user = await session.get(User, payment.user_id)
        session.add(
            AuditLog(
                actor_telegram_id=callback.from_user.id,
                action="manual_payment_rejected",
                target_type="payment",
                target_id=payment.id,
            )
        )
        await session.commit()
    await callback.answer("Заявка отклонена", show_alert=True)
    if user:
        await bot.send_message(
            user.telegram_id,
            "Заявка на пополнение отклонена. Если это ошибка, напишите в поддержку.\n"
            f"Заявка: <code>{payment.id[:8]}</code>",
        )


@router.callback_query(F.data.startswith("admin:payment:user:"))
async def admin_payment_user(callback: CallbackQuery, context: AppContext) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    payment_id = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        payment = await session.get(Payment, payment_id)
        user = await session.get(User, payment.user_id) if payment else None
        current = await wallet_balance(session, user.id) if user else Decimal("0")
    await callback.answer()
    if callback.message and user:
        await callback.message.answer(
            f"Telegram ID: <code>{user.telegram_id}</code>\n"
            f"Username: @{escape(user.username or '—')}\n"
            f"Баланс: <b>{format_rub(current)}</b>"
        )


@router.callback_query(F.data == "admin:features")
async def admin_features(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    async with context.db.sessions() as session:
        flags = list(
            (await session.scalars(select(FeatureFlag).order_by(FeatureFlag.sort_order))).all()
        )
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Нажмите, чтобы включить или выключить функцию:",
            reply_markup=admin_features_menu(flags),
        )


@router.callback_query(F.data.startswith("admin:feature:"))
async def admin_toggle_feature(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    key = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        flag = await session.get(FeatureFlag, key)
        if not flag:
            await callback.answer("Функция не найдена", show_alert=True)
            return
        flag.enabled = not flag.enabled
        session.add(
            AuditLog(
                actor_telegram_id=callback.from_user.id,
                action="feature_toggle",
                target_type="feature",
                target_id=key,
                details=f"enabled={flag.enabled}",
            )
        )
        await session.commit()
        flags = list(
            (await session.scalars(select(FeatureFlag).order_by(FeatureFlag.sort_order))).all()
        )
    await callback.answer("Настройка сохранена")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=admin_features_menu(flags))


@router.callback_query(F.data == "admin:templates")
async def admin_templates(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    async with context.db.sessions() as session:
        templates = list((await session.scalars(select(Template).order_by(Template.title))).all())
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Выберите стиль. Внутри можно изменить название, описание, "
            "инструкцию для ИИ и картинку:",
            reply_markup=admin_templates_menu(templates),
        )


@router.callback_query(F.data.startswith("admin:template_open:"))
async def admin_open_template(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    slug = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        template = await session.scalar(select(Template).where(Template.slug == slug))
    if not template:
        await callback.answer("Стиль не найден", show_alert=True)
        return
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    caption = (
        f"<b>{template.title}</b>\n"
        f"{template.description}\n\n"
        f"Статус: {'включён' if template.active else 'выключен'}"
    )
    preview = Path(template.preview_path) if template.preview_path else None
    if preview and preview.exists():
        await callback.message.answer_photo(
            FSInputFile(preview),
            caption=caption,
            reply_markup=admin_template_menu(template),
        )
    else:
        await callback.message.answer(
            caption + "\nКартинка пока не загружена.",
            reply_markup=admin_template_menu(template),
        )


@router.callback_query(F.data.startswith("admin:template_toggle:"))
async def admin_toggle_template_new(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    slug = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        template = await session.scalar(select(Template).where(Template.slug == slug))
        if not template:
            await callback.answer("Стиль не найден", show_alert=True)
            return
        template.active = not template.active
        template.version += 1
        session.add(
            AuditLog(
                actor_telegram_id=callback.from_user.id,
                action="template_toggle",
                target_type="template",
                target_id=template.id,
                details=f"enabled={template.active}",
            )
        )
        await session.commit()
    await callback.answer("Стиль включён" if template.active else "Стиль выключен")
    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"<b>{template.title}</b>: {'включён 🟢' if template.active else 'выключен ⚪️'}",
            reply_markup=admin_template_menu(template),
        )


@router.callback_query(F.data.startswith("admin:template_edit:"))
async def admin_edit_template(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer("Некорректная команда", show_alert=True)
        return
    slug, field = parts[2], parts[3]
    async with context.db.sessions() as session:
        template = await session.scalar(select(Template).where(Template.slug == slug))
    if not template:
        await callback.answer("Стиль не найден", show_alert=True)
        return
    await state.update_data(admin_template_slug=slug, admin_template_field=field)
    await callback.answer()
    if field == "preview":
        await state.set_state(AdminFlow.awaiting_template_preview)
        prompt = "Отправьте новую картинку-пример одним изображением."
    else:
        await state.set_state(AdminFlow.awaiting_template_value)
        prompts = {
            "title": f"Отправьте новое название.\nСейчас: {template.title}",
            "description": (f"Отправьте новое описание.\nСейчас:\n{template.description}"),
            "credits": (
                "Отправьте, сколько оплаченных стикеров списывать за один результат.\n"
                f"Сейчас: {template.credits}"
            ),
            "prompt": (
                "Отправьте новую инструкцию для нейросети. Она не показывается "
                f"пользователю.\n\nСейчас:\n{template.prompt}"
            ),
        }
        prompt = prompts.get(field, "Отправьте новое значение.")
    if callback.message:
        await callback.message.answer(prompt)


@router.message(AdminFlow.awaiting_template_value, F.text)
async def admin_save_template_value(
    message: Message,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        return
    data = await state.get_data()
    slug = str(data.get("admin_template_slug") or "")
    field = str(data.get("admin_template_field") or "")
    raw = (message.text or "").strip()
    if field == "title" and not 2 <= len(raw) <= 100:
        await message.answer("Название должно содержать от 2 до 100 символов.")
        return
    if field == "description" and not 5 <= len(raw) <= 1000:
        await message.answer("Описание должно содержать от 5 до 1000 символов.")
        return
    if field == "prompt" and not 20 <= len(raw) <= 8000:
        await message.answer("Инструкция должна содержать от 20 до 8000 символов.")
        return
    value: str | int = raw
    if field == "credits":
        try:
            value = int(raw)
        except ValueError:
            await message.answer("Отправьте целое число.")
            return
        if not 1 <= value <= 100:
            await message.answer("Допустимое значение — от 1 до 100 стикеров.")
            return
    if field not in {"title", "description", "credits", "prompt"}:
        await state.clear()
        await message.answer("Настройка не поддерживается.")
        return
    async with context.db.sessions() as session:
        template = await session.scalar(select(Template).where(Template.slug == slug))
        if not template:
            await state.clear()
            await message.answer("Стиль не найден.")
            return
        setattr(template, field, value)
        template.version += 1
        session.add(
            AuditLog(
                actor_telegram_id=message.from_user.id,
                action=f"template_edit_{field}",
                target_type="template",
                target_id=template.id,
            )
        )
        await session.commit()
    await state.clear()
    await message.answer(
        "Изменение сохранено ✅",
        reply_markup=admin_template_menu(template),
    )


@router.message(AdminFlow.awaiting_template_preview, F.photo)
async def admin_save_template_preview(
    message: Message,
    state: FSMContext,
    context: AppContext,
    bot: Bot,
) -> None:
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        return
    data = await state.get_data()
    slug = str(data.get("admin_template_slug") or "")
    if not message.photo:
        await message.answer("Отправьте изображение.")
        return
    destination = BytesIO()
    await bot.download(message.photo[-1].file_id, destination=destination)
    preview_dir = Path("assets/admin_previews")
    await asyncio.to_thread(preview_dir.mkdir, parents=True, exist_ok=True)
    preview_path = preview_dir / f"{slug}.jpg"
    await asyncio.to_thread(preview_path.write_bytes, destination.getvalue())
    async with context.db.sessions() as session:
        template = await session.scalar(select(Template).where(Template.slug == slug))
        if not template:
            await state.clear()
            await message.answer("Стиль не найден.")
            return
        template.preview_path = str(preview_path)
        template.version += 1
        session.add(
            AuditLog(
                actor_telegram_id=message.from_user.id,
                action="template_edit_preview",
                target_type="template",
                target_id=template.id,
            )
        )
        await session.commit()
    await state.clear()
    await message.answer(
        "Новая картинка сохранена ✅",
        reply_markup=admin_template_menu(template),
    )


@router.callback_query(F.data.startswith("admin:template:"))
async def admin_toggle_template(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    slug = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        template = await session.scalar(select(Template).where(Template.slug == slug))
        if not template:
            await callback.answer("Стиль не найден", show_alert=True)
            return
        template.active = not template.active
        template.version += 1
        session.add(
            AuditLog(
                actor_telegram_id=callback.from_user.id,
                action="template_toggle",
                target_type="template",
                target_id=template.id,
                details=f"active={template.active}",
            )
        )
        await session.commit()
        templates = list((await session.scalars(select(Template).order_by(Template.title))).all())
    await callback.answer("Настройка сохранена")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=admin_templates_menu(templates))


@router.callback_query(F.data == "admin:prices")
async def admin_prices(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    async with context.db.sessions() as session:
        packages = list(
            (
                await session.scalars(
                    select(Package).order_by(Package.sort_order, Package.amount_rub)
                )
            ).all()
        )
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "<b>Цены и тарифы</b>\n\n"
            "Базовая цена применяется к автоматическим пакетам. Для каждого пакета "
            "можно выбрать автоматический расчёт, скидку или свою итоговую цену.",
            reply_markup=admin_packages_menu(packages),
        )


async def _send_admin_photo_menu(
    target: Message,
    context: AppContext,
) -> None:
    keys = {
        "photo_base_price_rub",
        "meme_sticker_enabled",
        "meme_sticker_price_rub",
    }
    for scenario in PHOTO_SCENARIOS:
        keys.add(enabled_setting_key(scenario.key))
        keys.add(price_setting_key(scenario.key))
    values = await _settings_map(context, keys)
    base = parse_money(values.get("photo_base_price_rub", "99"))
    enabled = {
        scenario.key: setting_enabled(
            values.get(enabled_setting_key(scenario.key), "true")
        )
        for scenario in PHOTO_SCENARIOS
    }
    prices = {}
    for scenario in PHOTO_SCENARIOS:
        override = parse_money(values.get(price_setting_key(scenario.key), "0"))
        prices[scenario.key] = override if override > 0 else base
    meme_override = parse_money(values.get("meme_sticker_price_rub", "0"))
    meme_price = (
        meme_override
        if meme_override > 0
        else parse_money(await _setting(context, "sticker_base_price_rub", "99"))
    )
    await target.answer(
        "<b>Фото, фотообразы и мемы</b>\n\n"
        "Нажатие на название включает или выключает сценарий. Цена 0 в настройке "
        "сценария означает использование общей цены.",
        reply_markup=admin_photo_menu(
            PHOTO_SCENARIOS,
            enabled=enabled,
            prices=prices,
            base_price=base,
            meme_enabled=setting_enabled(
                values.get("meme_sticker_enabled", "true")
            ),
            meme_price=meme_price,
        ),
    )


@router.callback_query(F.data == "admin:photo")
async def admin_photo_settings(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    await callback.answer()
    if isinstance(callback.message, Message):
        await _send_admin_photo_menu(callback.message, context)


@router.callback_query(F.data.startswith("admin:photo_toggle:"))
async def admin_toggle_photo_scenario(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    key = (callback.data or "").rsplit(":", 1)[1]
    if key == "meme":
        setting_key = "meme_sticker_enabled"
    elif scenario_by_key(key):
        setting_key = enabled_setting_key(key)
    else:
        await callback.answer("Сценарий не найден", show_alert=True)
        return
    async with context.db.sessions() as session:
        setting = await session.get(BotSetting, setting_key)
        if not setting:
            await callback.answer("Настройка не найдена", show_alert=True)
            return
        setting.value = "false" if setting_enabled(setting.value) else "true"
        session.add(
            AuditLog(
                actor_telegram_id=callback.from_user.id,
                action="photo_scenario_toggle",
                target_type="bot_setting",
                target_id=setting_key,
                details=f"enabled={setting.value}",
            )
        )
        await session.commit()
    await callback.answer("Настройка сохранена")
    if isinstance(callback.message, Message):
        await _send_admin_photo_menu(callback.message, context)


@router.callback_query(F.data.startswith("admin:package_open:"))
async def admin_open_package(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    code = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        package = await session.scalar(select(Package).where(Package.code == code))
        effective_price = await package_price(session, package) if package else Decimal("0")
    if not package:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"<b>{package.title}</b>\n"
            f"Стикеров: {package.credits}\n"
            f"Цена: {format_rub(effective_price)}\n"
            f"Режим: {package.pricing_mode}\n"
            f"Статус: {'включён' if package.active else 'выключен'}",
            reply_markup=admin_package_menu(package),
        )


@router.callback_query(F.data.startswith("admin:package_toggle:"))
async def admin_toggle_package(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    code = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        package = await session.scalar(select(Package).where(Package.code == code))
        if not package:
            await callback.answer("Тариф не найден", show_alert=True)
            return
        package.active = not package.active
        package.version += 1
        session.add(
            AuditLog(
                actor_telegram_id=callback.from_user.id,
                action="package_toggle",
                target_type="package",
                target_id=package.id,
                details=f"enabled={package.active}",
            )
        )
        await session.commit()
    await callback.answer("Настройка сохранена")
    if callback.message:
        await callback.message.answer(
            f"{package.title}: {'включён 🟢' if package.active else 'выключен ⚪️'}",
            reply_markup=admin_package_menu(package),
        )


@router.callback_query(F.data.startswith("admin:package_edit:"))
async def admin_edit_package(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer("Некорректная команда", show_alert=True)
        return
    code, field = parts[2], parts[3]
    async with context.db.sessions() as session:
        package = await session.scalar(select(Package).where(Package.code == code))
    if not package:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    labels = {
        "title": f"Отправьте новое название.\nСейчас: {package.title}",
        "credits": f"Отправьте новое количество стикеров.\nСейчас: {package.credits}",
        "amount": (
            "Отправьте новую итоговую цену в рублях.\n"
            f"Сейчас: {format_rub(package.amount_rub)}"
        ),
        "discount": (
            "Отправьте скидку в процентах от 0 до 99.\n"
            f"Сейчас: {Decimal(package.discount_percent):g}%"
        ),
    }
    if field not in labels:
        await callback.answer("Настройка не поддерживается", show_alert=True)
        return
    await state.set_state(AdminFlow.awaiting_package_value)
    await state.update_data(admin_package_code=code, admin_package_field=field)
    await callback.answer()
    if callback.message:
        await callback.message.answer(labels[field])


@router.message(AdminFlow.awaiting_package_value, F.text)
async def admin_save_package_value(
    message: Message,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        return
    data = await state.get_data()
    code = str(data.get("admin_package_code") or "")
    field = str(data.get("admin_package_field") or "")
    raw = (message.text or "").strip().replace(",", ".")
    value: str | int | Decimal
    if field == "title":
        if not 2 <= len(raw) <= 100:
            await message.answer("Название должно содержать от 2 до 100 символов.")
            return
        value = raw
        model_field = "title"
    elif field == "credits":
        try:
            value = int(raw)
        except ValueError:
            await message.answer("Отправьте целое число.")
            return
        if value not in SUPPORTED_STICKER_QUANTITIES:
            allowed = ", ".join(str(item) for item in SUPPORTED_STICKER_QUANTITIES)
            await message.answer(f"Допустимые наборы: {allowed} стикеров.")
            return
        model_field = "credits"
    elif field == "amount":
        try:
            value = Decimal(raw).quantize(Decimal("0.01"))
        except InvalidOperation:
            await message.answer("Отправьте цену числом, например 299 или 299.90.")
            return
        if not Decimal("1") <= value <= Decimal("1000000"):
            await message.answer("Допустимая цена — от 1 до 1000000 ₽.")
            return
        model_field = "amount_rub"
    elif field == "discount":
        try:
            value = Decimal(raw).quantize(Decimal("0.01"))
        except InvalidOperation:
            await message.answer("Отправьте процент числом, например 10.")
            return
        if not Decimal("0") <= value <= Decimal("99"):
            await message.answer("Допустимая скидка — от 0 до 99%.")
            return
        model_field = "discount_percent"
    else:
        await state.clear()
        await message.answer("Настройка не поддерживается.")
        return
    async with context.db.sessions() as session:
        package = await session.scalar(select(Package).where(Package.code == code))
        if not package:
            await state.clear()
            await message.answer("Тариф не найден.")
            return
        if field == "credits":
            duplicate = await session.scalar(
                select(Package).where(
                    Package.credits == value,
                    Package.id != package.id,
                )
            )
            if duplicate:
                await message.answer(
                    "Набор с таким количеством стикеров уже существует."
                )
                return
        setattr(package, model_field, value)
        if field == "amount":
            package.pricing_mode = "custom"
        if field == "discount":
            package.pricing_mode = "discount"
            package.amount_rub = await package_price(session, package)
        package.version += 1
        session.add(
            AuditLog(
                actor_telegram_id=message.from_user.id,
                action=f"package_edit_{field}",
                target_type="package",
                target_id=package.id,
            )
        )
        await session.commit()
    await state.clear()
    await message.answer(
        "Изменение сохранено ✅",
        reply_markup=admin_package_menu(package),
    )


@router.callback_query(F.data.startswith("admin:package_mode:"))
async def admin_package_mode(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    code = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        package = await session.scalar(select(Package).where(Package.code == code))
    if not package:
        await callback.answer("Пакет не найден", show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Выберите способ расчёта цены:",
            reply_markup=admin_package_mode_menu(package),
        )


@router.callback_query(F.data.startswith("admin:package_set_mode:"))
async def admin_set_package_mode(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or parts[3] not in {"automatic", "discount", "custom"}:
        await callback.answer("Некорректный режим", show_alert=True)
        return
    code, mode = parts[2], parts[3]
    async with context.db.sessions() as session:
        package = await session.scalar(select(Package).where(Package.code == code))
        if not package:
            await callback.answer("Пакет не найден", show_alert=True)
            return
        package.pricing_mode = mode
        if mode in {"automatic", "discount"}:
            package.amount_rub = await package_price(session, package)
        package.version += 1
        await session.commit()
    await callback.answer("Режим цены сохранён")
    if callback.message:
        await callback.message.answer(
            f"{package.title}: {format_rub(package.amount_rub)}",
            reply_markup=admin_package_mode_menu(package),
        )


@router.callback_query(F.data == "admin:packages_recalculate")
async def admin_recalculate_packages(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    async with context.db.sessions() as session:
        await recalculate_package_prices(session)
    await callback.answer("Автоматические цены пересчитаны", show_alert=True)


@router.callback_query(F.data == "admin:texts")
async def admin_texts(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    async with context.db.sessions() as session:
        settings = list(
            (await session.scalars(select(BotSetting).order_by(BotSetting.title))).all()
        )
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Выберите сообщение, которое хотите изменить:",
            reply_markup=admin_texts_menu(settings),
        )


@router.callback_query(F.data == "admin:documents")
async def admin_documents(callback: CallbackQuery, context: AppContext) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Выберите документ, который хотите изменить:",
            reply_markup=admin_documents_menu(),
        )


@router.callback_query(F.data.startswith("admin:document_edit:"))
async def admin_edit_document(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    document = (callback.data or "").rsplit(":", 1)[1]
    definition = LEGAL_DOCUMENTS.get(document)
    if not definition:
        await callback.answer("Документ не найден", show_alert=True)
        return
    await state.set_state(AdminFlow.awaiting_document_value)
    await state.update_data(admin_document=document)
    await callback.answer()
    if callback.message:
        await callback.message.answer(f"<b>{definition[1]}</b>\n\nТекущий текст:")
        await callback.message.answer(await _legal_text(context, document))
        await callback.message.answer(
            "Отправьте полный новый текст одним сообщением.\n"
            "Чтобы вернуть стандартный шаблон, отправьте: <code>СБРОСИТЬ</code>"
        )


@router.message(AdminFlow.awaiting_document_value, F.text)
async def admin_save_document(
    message: Message,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        return
    data = await state.get_data()
    document = str(data.get("admin_document") or "")
    definition = LEGAL_DOCUMENTS.get(document)
    if not definition:
        await state.clear()
        await message.answer("Документ не найден.")
        return
    raw = (message.text or "").strip()
    reset = raw.upper() == "СБРОСИТЬ"
    if not reset and not 10 <= len(raw) <= 3900:
        await message.answer("Текст должен содержать от 10 до 3900 символов.")
        return
    setting_key, title = definition
    async with context.db.sessions() as session:
        setting = await session.get(BotSetting, setting_key)
        if reset:
            if setting:
                await session.delete(setting)
        elif setting:
            setting.value = raw
        else:
            session.add(BotSetting(key=setting_key, title=title, value=raw))
        session.add(
            AuditLog(
                actor_telegram_id=message.from_user.id,
                action="legal_document_edit",
                target_type="bot_setting",
                target_id=setting_key,
            )
        )
        await session.commit()
    await state.clear()
    result = "Стандартный шаблон восстановлен ✅" if reset else "Документ сохранён ✅"
    await message.answer(result, reply_markup=admin_documents_menu())


@router.callback_query(F.data == "admin:welcome_image")
async def admin_welcome_image(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    await state.set_state(AdminFlow.awaiting_welcome_image)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "<b>Картинка приветствия</b>\n\n"
            "Отправьте новую картинку именно как фотографию. "
            "Она будет показываться вместе с приветственным текстом."
        )


@router.message(AdminFlow.awaiting_welcome_image, F.photo)
async def admin_save_welcome_image(
    message: Message,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        return
    file_id = message.photo[-1].file_id
    async with context.db.sessions() as session:
        setting = await session.get(BotSetting, "welcome_image_file_id")
        if setting:
            setting.value = file_id
        else:
            session.add(
                BotSetting(
                    key="welcome_image_file_id",
                    title="Картинка приветствия",
                    value=file_id,
                )
            )
        session.add(
            AuditLog(
                actor_telegram_id=message.from_user.id,
                action="welcome_image_edit",
                target_type="bot_setting",
                target_id="welcome_image_file_id",
            )
        )
        await session.commit()
    await state.clear()
    await message.answer_photo(
        file_id,
        caption="Картинка приветствия сохранена ✅",
        reply_markup=admin_menu(),
    )


@router.message(Command("admin"))
async def admin(message: Message, context: AppContext) -> None:
    # Normally handled by the gateway router. Kept as a safe fallback.
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        await message.answer("Команда недоступна.")
        return
    await _send_generation_admin(message, context)


@router.callback_query(F.data == "admin:section:ai")
async def open_generation_admin(callback: CallbackQuery, context: AppContext) -> None:
    if callback.from_user.id not in context.settings.admin_ids:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.answer()
    if isinstance(callback.message, Message):
        await _send_generation_admin(callback.message, context)


@router.message(AdminFlow.awaiting_welcome_image)
async def admin_welcome_image_invalid(message: Message) -> None:
    await message.answer(
        "Нужно отправить изображение как фотографию, а не как файл или текст."
    )


@router.callback_query(F.data.startswith("admin:text_edit:"))
async def admin_edit_text(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    key = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        setting = await session.get(BotSetting, key)
    if not setting or key == "credit_display_price_rub":
        await callback.answer("Текст не найден", show_alert=True)
        return
    await state.set_state(AdminFlow.awaiting_setting_value)
    await state.update_data(admin_setting_key=key)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"<b>{setting.title}</b>\n\nСейчас:\n{setting.value}\n\n"
            "Отправьте новый текст одним сообщением."
        )


@router.message(AdminFlow.awaiting_setting_value, F.text)
async def admin_save_setting(
    message: Message,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        return
    data = await state.get_data()
    key = str(data.get("admin_setting_key") or "")
    raw = (message.text or "").strip()
    money_keys = {
        "sticker_base_price_rub",
        "video_price_rub",
        "photo_base_price_rub",
        "custom_topup_min_rub",
        "custom_topup_max_rub",
    }
    override_money_keys = {
        "meme_sticker_price_rub",
        *(price_setting_key(scenario.key) for scenario in PHOTO_SCENARIOS),
    }
    if key in money_keys or key in override_money_keys:
        try:
            price = parse_money(raw)
        except ValueError:
            await message.answer("Отправьте сумму числом, например 299.")
            return
        minimum = Decimal("0") if key in override_money_keys else Decimal("1")
        if not minimum <= price <= Decimal("1000000"):
            await message.answer(
                f"Допустимое значение — от {minimum:g} до 1000000 ₽."
            )
            return
        raw = f"{price:.2f}"
    elif key == "video_duration_seconds":
        try:
            duration = int(raw)
        except ValueError:
            await message.answer("Отправьте целое число секунд.")
            return
        if not 2 <= duration <= 10:
            await message.answer("Допустимая длительность — от 2 до 10 секунд.")
            return
        raw = str(duration)
    elif key == "topup_amounts_rub":
        try:
            amounts = parse_amount_list(raw)
        except ValueError:
            await message.answer("Пример: 99,500,1000,2000,5000")
            return
        if not amounts:
            await message.answer("Укажите хотя бы одну сумму.")
            return
        raw = ",".join(f"{amount:.2f}" for amount in amounts)
    elif key == "manual_payment_url":
        if raw in {"-", "нет", "удалить"}:
            raw = ""
        elif raw and not raw.startswith("https://"):
            await message.answer("Ссылка должна начинаться с https://")
            return
    elif key == "credit_display_price_rub":
        await state.clear()
        await message.answer("Эта устаревшая настройка больше не используется.")
        return
    elif not 2 <= len(raw) <= 3500:
        await message.answer("Текст должен содержать от 2 до 3500 символов.")
        return
    async with context.db.sessions() as session:
        setting = await session.get(BotSetting, key)
        if not setting:
            await state.clear()
            await message.answer("Настройка не найдена.")
            return
        setting.value = raw
        if key == "sticker_base_price_rub":
            await recalculate_package_prices(session)
        session.add(
            AuditLog(
                actor_telegram_id=message.from_user.id,
                action="bot_setting_edit",
                target_type="bot_setting",
                target_id=key,
            )
        )
        await session.commit()
    await state.clear()
    await message.answer("Настройка сохранена ✅", reply_markup=admin_menu())


async def _send_admin_tickets(
    callback: CallbackQuery,
    context: AppContext,
    *,
    scope: str,
) -> None:
    query = select(SupportTicket)
    if scope == "open":
        query = query.where(
            SupportTicket.status.in_(
                {
                    TicketStatus.NEW.value,
                    TicketStatus.IN_PROGRESS.value,
                    TicketStatus.WAITING_USER.value,
                }
            )
        )
    async with context.db.sessions() as session:
        tickets = list(
            (await session.scalars(query.order_by(SupportTicket.created_at.desc()).limit(20))).all()
        )
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            ("<b>Открытые обращения</b>" if scope == "open" else "<b>Все последние обращения</b>")
            + ("\nВыберите обращение:" if tickets else "\nОбращений пока нет."),
            reply_markup=admin_tickets_menu(tickets, scope=scope),
        )


@router.callback_query(F.data == "admin:tickets")
@router.callback_query(F.data == "admin:tickets:open")
async def admin_tickets(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    await _send_admin_tickets(callback, context, scope="open")


@router.callback_query(F.data == "admin:tickets:all")
async def admin_tickets_all(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    await _send_admin_tickets(callback, context, scope="all")


@router.callback_query(F.data.startswith("admin:ticket_open:"))
async def admin_open_ticket(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    ticket_id = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        ticket = await session.get(SupportTicket, ticket_id)
        user = await session.get(User, ticket.user_id) if ticket else None
    if not ticket:
        await callback.answer("Обращение не найдено", show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"<b>Обращение {ticket.id[:8]}</b>\n"
            f"Статус: {TICKET_STATUS_LABELS.get(ticket.status, ticket.status)}\n"
            f"Пользователь: <code>{user.telegram_id if user else 'не найден'}</code>\n\n"
            f"{escape(ticket.message)}"
            + (f"\n\n<b>Ответ:</b>\n{escape(ticket.admin_reply)}" if ticket.admin_reply else ""),
            reply_markup=admin_ticket_menu(ticket),
        )


@router.callback_query(F.data.startswith("admin:ticket_reply:"))
async def admin_start_ticket_reply(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    ticket_id = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        ticket = await session.get(SupportTicket, ticket_id)
    if not ticket:
        await callback.answer("Обращение не найдено", show_alert=True)
        return
    await state.set_state(AdminFlow.awaiting_ticket_reply)
    await state.update_data(admin_ticket_id=ticket_id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"Напишите ответ на обращение <code>{ticket.id[:8]}</code> одним сообщением."
        )


@router.message(AdminFlow.awaiting_ticket_reply, F.text)
async def admin_send_ticket_reply(
    message: Message,
    state: FSMContext,
    context: AppContext,
    bot: Bot,
) -> None:
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        return
    data = await state.get_data()
    ticket_id = str(data.get("admin_ticket_id") or "")
    reply = (message.text or "").strip()
    if not 1 <= len(reply) <= 3500:
        await message.answer("Ответ должен содержать от 1 до 3500 символов.")
        return
    async with context.db.sessions() as session:
        ticket = await session.get(SupportTicket, ticket_id)
        if not ticket:
            await state.clear()
            await message.answer("Обращение не найдено.")
            return
        user = await session.get(User, ticket.user_id)
        ticket.admin_reply = reply
        ticket.status = TicketStatus.RESOLVED.value
        session.add(
            AuditLog(
                actor_telegram_id=message.from_user.id,
                action="ticket_reply",
                target_type="support_ticket",
                target_id=ticket.id,
            )
        )
        await session.commit()
    if user:
        await bot.send_message(
            user.telegram_id,
            f"Ответ поддержки по обращению <code>{ticket.id[:8]}</code>:\n\n{escape(reply)}",
        )
    await state.clear()
    await message.answer(
        "Ответ отправлен ✅",
        reply_markup=admin_ticket_menu(ticket),
    )


@router.callback_query(F.data.startswith("admin:ticket_close:"))
async def admin_close_ticket(
    callback: CallbackQuery,
    context: AppContext,
) -> None:
    if not await _admin_callback_allowed(callback, context):
        return
    ticket_id = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        ticket = await session.get(SupportTicket, ticket_id)
        if not ticket:
            await callback.answer("Обращение не найдено", show_alert=True)
            return
        ticket.status = TicketStatus.CLOSED.value
        session.add(
            AuditLog(
                actor_telegram_id=callback.from_user.id,
                action="ticket_close",
                target_type="support_ticket",
                target_id=ticket.id,
            )
        )
        await session.commit()
    await callback.answer("Обращение закрыто")
    if callback.message:
        await callback.message.answer(
            f"Обращение <code>{ticket.id[:8]}</code> закрыто ✅",
            reply_markup=admin_ticket_menu(ticket),
        )


@router.message(Command("admin_user"))
async def admin_user(message: Message, context: AppContext) -> None:
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /admin_user TELEGRAM_ID")
        return
    telegram_id = int(parts[1])
    async with context.db.sessions() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if not user:
            await message.answer("Пользователь не найден.")
            return
        value = await wallet_balance(session, user.id)
    await message.answer(
        f"ID: <code>{user.telegram_id}</code>\n"
        f"Username: @{user.username or '—'}\n"
        f"Баланс: <b>{format_rub(value)}</b>"
    )


@router.message(Command("admin_balance"))
@router.message(Command("admin_credit"))
async def admin_credit(message: Message, context: AppContext) -> None:
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        return
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer(
            "Использование: /admin_balance TELEGRAM_ID СУММА [комментарий]"
        )
        return
    try:
        amount = parse_money(parts[2])
    except ValueError:
        await message.answer("Сумма должна быть числом.")
        return
    if amount == 0 or abs(amount) > Decimal("1000000"):
        await message.answer("Допустима ненулевая сумма до 1 000 000 ₽.")
        return
    comment = parts[3] if len(parts) == 4 else "Ручная корректировка"
    async with context.db.sessions() as session:
        user = await session.scalar(select(User).where(User.telegram_id == int(parts[1])))
        if not user:
            await message.answer("Пользователь не найден.")
            return
        entry_key = f"admin:{message.from_user.id}:{message.message_id}:wallet"
        await add_wallet_entry(
            session,
            user_id=user.id,
            amount_rub=amount,
            entry_type="manual_adjustment",
            idempotency_key=entry_key,
            reference_type="admin",
            comment=comment,
        )
        session.add(
            AuditLog(
                actor_telegram_id=message.from_user.id,
                action="wallet_adjustment",
                target_type="user",
                target_id=user.id,
                details=f"amount_rub={amount}; comment={comment}",
            )
        )
        await session.commit()
        new_balance = await wallet_balance(session, user.id)
    await message.answer(f"Готово. Новый баланс: <b>{format_rub(new_balance)}</b>")


@router.message(Command("admin_ticket"))
async def admin_ticket(message: Message, context: AppContext, bot: Bot) -> None:
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) != 3:
        await message.answer("Использование: /admin_ticket ID_ОБРАЩЕНИЯ ОТВЕТ")
        return
    async with context.db.sessions() as session:
        ticket = await session.get(SupportTicket, parts[1])
        if not ticket:
            ticket = await session.scalar(
                select(SupportTicket).where(SupportTicket.id.startswith(parts[1]))
            )
        if not ticket:
            await message.answer("Обращение не найдено.")
            return
        user = await session.get(User, ticket.user_id)
        ticket.admin_reply = parts[2]
        ticket.status = TicketStatus.RESOLVED.value
        session.add(
            AuditLog(
                actor_telegram_id=message.from_user.id,
                action="ticket_reply",
                target_type="support_ticket",
                target_id=ticket.id,
            )
        )
        await session.commit()
    if user:
        await bot.send_message(
            user.telegram_id,
            f"Ответ поддержки по обращению <code>{ticket.id[:8]}</code>:\n\n{escape(parts[2])}",
        )
    await message.answer("Ответ отправлен.")


async def setup_commands(bot: Bot, context: AppContext) -> None:
    commands = [
        BotCommand(command="start", description="Открыть кнопочное меню"),
    ]
    await bot.set_my_commands(commands)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    for admin_id in context.settings.admin_ids:
        await bot.set_my_commands(
            commands
            + [
                BotCommand(command="admin", description="Открыть админ-панель"),
                BotCommand(command="admin_balance", description="Изменить баланс пользователя"),
            ],
            scope=BotCommandScopeChat(chat_id=admin_id),
        )


def build_dispatcher(context: AppContext) -> Dispatcher:
    storage = (
        RedisStorage.from_url(context.settings.redis_url)
        if context.settings.redis_url
        else MemoryStorage()
    )
    dispatcher = Dispatcher(storage=storage)
    dispatcher.update.outer_middleware(StoreDatabaseMiddleware(store_session_maker))
    dispatcher.include_router(storefront_router)
    dispatcher.include_router(router)
    dispatcher.include_router(setup_store_routers())
    dispatcher["context"] = context
    return dispatcher
