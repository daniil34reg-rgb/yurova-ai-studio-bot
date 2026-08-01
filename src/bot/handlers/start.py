import re
from html import escape

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.content import DEFAULT_BANK_CHOICE_TEXT, build_default_payment_instruction
from bot.keyboards import (
    back_kb,
    bank_choice_kb,
    buy_sticker_with_phone_kb,
    main_menu_kb,
    my_phone_kb,
    payment_result_kb,
    phone_request_kb,
    remove_reply_kb,
    sticker_count_kb,
)
from bot.keyboards.keyboards import sticker_buttons_kb
from bot.models import Promotion
from bot.repositories import PromotionQRRepository, PromotionRepository, SettingsRepository, UserRepository, \
    StickerButtonRepository
from bot.services import UserService, schedule_qr_deletion
from bot.states import GiveawayStates

router = Router()

WARNING_TEXT = (
    "* если в боте выше, вы видите\n"
    "ссылки на сторонние каналы,\n"
    "сообщаем вам, что они никак не\n"
    "связаны с каналами Yurov CLUB. Это могут\n"
    "быть мошенники. За них\n"
    "ответственность мы не несем.\n"
    "Будьте осторожны ⚠️"
)

PHONE_TEXT = (
    "Введите ваш номер телефона 📞\n"
    "Пример: +79000000000\n\n"
    "Если у вас возникли какие то проблемы,\n"
    "пожалуйста, напишите администратору\n"
    f"@yurov_support"
)

SAVED_PHONE_TEXT = (
    "Ваши данные сохранены, нажмите\n"
    "\"Купить стикер\" для продолжения\n\n"
)

BANK_TEXT = DEFAULT_BANK_CHOICE_TEXT
BANK_CHOICE_TEXT_KEY = "bank_choice_text"
PAYMENT_MANAGER_USERNAME_KEY = "payment_manager_username"
WARNING_TEXT_KEY = "warning_text"
MAIN_JOIN_BUTTON_LABEL_KEY = "main_join_button_label"
PAYMENT_INSTRUCTION_TEXT_KEY = "payment_instruction_text"

STICKERS_TEXT = (
    "Сколько стикеров вы хотите\n"
    "приобрести?"
)

HOW_TO_PAY_TEXT = (
    "Наш менеджер уже начал\n"
    "обрабатывать заявки на эту\n"
    "Акцию.\n\n"
    "Если вы все сделали правильно и\n"
    "отправили:\n"
    "1. Чек\n"
    "2. Ваше ФИО\n"
    "3. Контактный номер телефона\n"
    f"сюда @{settings.payment_manager_username}\n\n"
    "То спокойно ожидайте присвоения\n"
    "номера.\n\n"
    "Ответ может занимать до 24 часов\n\n"
    "Главное, после того что вы\n"
    "отправили менеджеру выше, не\n"
    "писать новые сообщения! Иначе\n"
    "вы уйдете в конец очереди"
)

NO_PROMO_TEXT = (
    "📌 Добро пожаловать в наш бот\n\n"
    "На данный момент активных акций нет.\n"
    "Следите за обновлениями! 👀"
)

def _with_warning(text: str, warning: str) -> str:
    return f"{text.rstrip()}\n\n{warning}" if warning.strip() else text.rstrip()


async def _warning_text(session: AsyncSession) -> str:
    return await SettingsRepository(session).get(WARNING_TEXT_KEY, WARNING_TEXT)


async def _saved_phone_text(promo, session: AsyncSession) -> str:
    if promo and promo.description:
        text = promo.description
    else:
        text = SAVED_PHONE_TEXT
    return _with_warning(text, await _warning_text(session))


async def _bank_choice_text(session: AsyncSession) -> str:
    custom_text = await SettingsRepository(session).get(BANK_CHOICE_TEXT_KEY, "")
    return _with_warning(custom_text or BANK_TEXT, await _warning_text(session))


async def _payment_manager_username(session: AsyncSession) -> str:
    custom_username = await SettingsRepository(session).get(PAYMENT_MANAGER_USERNAME_KEY, "")
    return (custom_username or settings.payment_manager_username).lstrip("@")

def _calc_prices(base: float) -> dict[int, str]:
    return {
        1:  f"{base:.2f}",
        2:  f"{base * 2:.2f}",
        3:  f"{base * 3:.2f}",
        5:  f"{base * 5:.2f}",
        10: f"{base * 10:.2f}",
    }

async def _get_stickers_text(session: AsyncSession) -> str:
    text = await SettingsRepository(session).get("stickers_text", STICKERS_TEXT)
    return _with_warning(text, await _warning_text(session))


async def _main_menu_keyboard(session: AsyncSession, show_admin: bool):
    label = await SettingsRepository(session).get(MAIN_JOIN_BUTTON_LABEL_KEY, "УЧАСТВОВАТЬ")
    return main_menu_kb(show_admin, label or "УЧАСТВОВАТЬ")

async def _welcome_text(promotions: list, session: AsyncSession) -> str:
    custom = await SettingsRepository(session).get("welcome_text", "")
    warning = await _warning_text(session)
    if custom:
        prizes_list = "\n".join(f"• {p.prize_name}" for p in promotions)
        prize_first = promotions[0].prize_name if promotions else ""
        return _with_warning((
            custom
            .replace("{prizes}", prizes_list)
            .replace("{prize}", prize_first)
        ), warning)

    if len(promotions) == 1:
        return _with_warning((
            "📌 Добро пожаловать в наш бот\n\n"
            "Сегодня у нас в акции:\n"
            f"{promotions[0].prize_name}\n\n"
            "Для продолжения, пожалуйста\n"
            "нажмите кнопку участия."
        ), warning)
    prizes = "\n".join(f"• {p.prize_name}" for p in promotions)
    return _with_warning((
        "📌 Добро пожаловать в наш бот\n\n"
        "Сегодня у нас в акциях:\n"
        f"{prizes}\n\n"
        "Для продолжения, пожалуйста\n"
        "нажмите кнопку участия."
    ), warning)

async def _payment_text_default(
    session: AsyncSession,
    promo,
    manager_username: str | None = None,
    total: str | None = None,
    count: int | None = None,
) -> str:
    price = promo.price_per_sticker if promo else 0
    manager_username = manager_username or settings.payment_manager_username
    total = total or f"{price:.2f}"

    common_text = await SettingsRepository(session).get(PAYMENT_INSTRUCTION_TEXT_KEY, "")
    template = promo.payment_text if promo and promo.payment_text else common_text
    if template:
        text = (
            template
            .replace("{price}", f"{price:.2f}")
            .replace("{total}", total)
            .replace("{count}", str(count) if count is not None else "")
            .replace("{manager}", f"@{manager_username.lstrip('@')}")
        )
        return _with_warning(text, await _warning_text(session))

    text = build_default_payment_instruction(
        price=f"{price:.2f}",
        manager=manager_username,
        support=settings.support_username,
    )
    return _with_warning(text, await _warning_text(session))


async def _payment_result_keyboard(session: AsyncSession, manager: str, payment_url: str | None):
    repo = SettingsRepository(session)

    async def enabled(key: str, default: bool = True) -> bool:
        return (await repo.get(f"post_{key}_enabled", "1" if default else "0")) != "0"

    return payment_result_kb(
        manager,
        payment_url,
        send_receipt_label=await repo.get("post_send_receipt_label", "🧾 ОТПРАВИТЬ ЧЕК МЕНЕДЖЕРУ ↗"),
        show_send_receipt=await enabled("send_receipt"),
        buy_again_label=await repo.get("post_buy_again_label", "Купить ещё"),
        show_buy_again=await enabled("buy_again"),
        how_to_pay_label=await repo.get("post_how_to_pay_label", "Как оплатить ❓"),
        show_how_to_pay=await enabled("how_to_pay"),
        where_number_label=await repo.get("post_where_number_label", "Где мой номер?"),
        show_where_number=await enabled("where_number"),
    )


def _normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D+", "", raw.strip())
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or not digits.startswith("7"):
        return None
    return "+7" + digits[1:]


async def _active_promotion(session: AsyncSession) -> Promotion | None:
    return await PromotionRepository(session).get_active()


async def _send_car(
    message: Message,
    caption: str,
    reply_markup,
    promotion: Promotion | None = None,
    photo_file_id: str | None = None,
) -> None:
    photo = photo_file_id or (promotion.photo_file_id if promotion else None)
    if photo:
        await message.answer_photo(photo=photo, caption=caption, reply_markup=reply_markup)
    else:
        await message.answer(caption, reply_markup=reply_markup)


async def _answer_car(callback: CallbackQuery, caption: str, reply_markup, promotion: Promotion | None = None) -> None:
    if promotion and promotion.photo_file_id:
        await callback.message.answer_photo(photo=promotion.photo_file_id, caption=caption, reply_markup=reply_markup)
    else:
        await callback.message.answer(caption, reply_markup=reply_markup)
    await callback.answer()


async def _show_payment_method(
    message: Message,
    session: AsyncSession,
    promo: Promotion,
    method,
    count: int,
    total: str,
) -> None:
    manager = await _payment_manager_username(session)
    caption = await _payment_text_default(
        session,
        promo,
        manager_username=manager,
        total=total,
        count=count,
    )
    keyboard = await _payment_result_keyboard(session, manager, getattr(method, "payment_url", None))
    if getattr(method, "file_id", None):
        sent_message = await message.answer_photo(
            photo=method.file_id,
            caption=caption,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        await schedule_qr_deletion(
            session,
            chat_id=sent_message.chat.id,
            message_id=sent_message.message_id,
        )
    else:
        await message.answer(caption, reply_markup=keyboard, parse_mode="HTML")


async def _continue_purchase(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    promo: Promotion,
    count: int,
) -> bool:
    methods = await PromotionQRRepository(session).list_for_promo(promo.id)
    if not methods:
        await message.answer("Для этой акции пока не настроены способы оплаты.")
        return False

    total = f"{promo.price_per_sticker * count:.2f}"
    await state.update_data(
        promotion_id=promo.id,
        purchase_count=count,
        purchase_total=total,
        qr_id=None,
    )

    if len(methods) > 1:
        bank_text = await _bank_choice_text(session)
        await _send_car(message, bank_text, bank_choice_kb(methods), promo)
        return True

    await state.update_data(qr_id=methods[0].id)
    await _show_payment_method(message, session, promo, methods[0], count, total)
    return True


# ── Handlers ──────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await UserService(UserRepository(session)).register_or_update(message.from_user)
    show_admin = message.from_user.id in settings.admin_ids
    promotions = await PromotionRepository(session).get_all_active()
    keyboard = await _main_menu_keyboard(session, show_admin)
    if not promotions:
        await message.answer(NO_PROMO_TEXT, reply_markup=keyboard)
        return
    text = await _welcome_text(promotions, session)
    main_menu_photo = await SettingsRepository(session).get("main_menu_photo_file_id", "")
    if main_menu_photo:
        await message.answer_photo(photo=main_menu_photo, caption=text, reply_markup=keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "giveaway_join")
async def giveaway_join(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    promotions = await PromotionRepository(session).get_all_active()
    if not promotions:
        await callback.answer("Активных акций нет.", show_alert=True)
        return

    if len(promotions) == 1:
        await state.update_data(promotion_id=promotions[0].id)
        user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
        if user and user.phone_number and user.customer_full_name and user.city:
            await _answer_car(
                callback,
                await _saved_phone_text(promotions[0], session),
                buy_sticker_with_phone_kb(),
                promotions[0],
            )
            return
        if not user or not user.phone_number:
            await state.set_state(GiveawayStates.waiting_phone)
            await callback.message.answer(PHONE_TEXT, reply_markup=phone_request_kb())
        elif not user.customer_full_name:
            await state.set_state(GiveawayStates.waiting_full_name)
            await callback.message.answer("Введите ваши ФИО полностью:", reply_markup=remove_reply_kb())
        else:
            await state.set_state(GiveawayStates.waiting_city)
            await callback.message.answer("Введите ваш город:", reply_markup=remove_reply_kb())
        await callback.answer()
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    for promo in promotions:
        builder.button(text=promo.prize_name, callback_data=f"select_promo:{promo.id}")
    builder.adjust(1)
    await callback.message.answer("🎯 Выберите акцию:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("select_promo:"))
async def select_promo(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    promo_id = int(callback.data.split(":", 1)[1])
    promo = await PromotionRepository(session).get(promo_id)
    if not promo or not promo.is_active:
        await callback.answer("Акция недоступна.", show_alert=True)
        return
    await state.update_data(promotion_id=promo_id)
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    if user and user.phone_number and user.customer_full_name and user.city:
        await _answer_car(callback, await _saved_phone_text(promo, session), buy_sticker_with_phone_kb(), promo)
        return
    if not user or not user.phone_number:
        await state.set_state(GiveawayStates.waiting_phone)
        await callback.message.answer(PHONE_TEXT, reply_markup=phone_request_kb())
    elif not user.customer_full_name:
        await state.set_state(GiveawayStates.waiting_full_name)
        await callback.message.answer("Введите ваши ФИО полностью:", reply_markup=remove_reply_kb())
    else:
        await state.set_state(GiveawayStates.waiting_city)
        await callback.message.answer("Введите ваш город:", reply_markup=remove_reply_kb())
    await callback.answer()


@router.callback_query(F.data == "my_phone")
async def my_phone(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    phone = user.phone_number if user else "не указан"
    full_name = user.customer_full_name if user and user.customer_full_name else "не указано"
    city = user.city if user and user.city else "не указан"
    await callback.message.answer(
        "👤 <b>Мои данные</b>\n\n"
        f"ФИО: <b>{escape(full_name)}</b>\n"
        f"Город: <b>{escape(city)}</b>\n"
        f"Телефон: <code>{phone}</code>",
        reply_markup=my_phone_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "change_phone")
async def change_phone(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(profile_edit_only=True)
    await state.set_state(GiveawayStates.waiting_phone)
    await callback.message.answer(PHONE_TEXT, reply_markup=phone_request_kb())
    await callback.answer()


@router.message(GiveawayStates.waiting_phone)
async def receive_phone(message: Message, session: AsyncSession, state: FSMContext) -> None:
    raw_phone = message.contact.phone_number if message.contact else (message.text or "")
    phone = _normalize_phone(raw_phone)
    if not phone:
        await message.answer(
            "❌ Неверный формат номера!\n\n"
            "Номер должен начинаться с +7 и содержать 11 цифр.\n"
            "Пример: +79001234567\n\n"
            "Попробуйте ещё раз 👇",
            reply_markup=phone_request_kb(),
        )
        return
    await UserService(UserRepository(session)).save_phone(message.from_user.id, phone)
    await message.answer("Номер сохранен.", reply_markup=remove_reply_kb())
    data = await state.get_data()
    if data.get("profile_edit_only"):
        await _finish_profile_setup(message, state, session)
        return
    await state.set_state(GiveawayStates.waiting_full_name)
    await message.answer("Теперь введите ваши ФИО полностью:")


@router.message(GiveawayStates.waiting_full_name)
async def receive_full_name(message: Message, session: AsyncSession, state: FSMContext) -> None:
    full_name = " ".join((message.text or "").split())
    if len(full_name) < 5:
        await message.answer("Введите ФИО полностью. Например: Иванов Иван Иванович")
        return
    await UserService(UserRepository(session)).save_customer_full_name(message.from_user.id, full_name)
    data = await state.get_data()
    if data.get("profile_edit_only"):
        await _finish_profile_setup(message, state, session)
        return
    await state.set_state(GiveawayStates.waiting_city)
    await message.answer("ФИО сохранено. Теперь введите ваш город:")


@router.message(GiveawayStates.waiting_city)
async def receive_city(message: Message, session: AsyncSession, state: FSMContext) -> None:
    city = " ".join((message.text or "").split())
    if len(city) < 2:
        await message.answer("Введите название города.")
        return
    await UserService(UserRepository(session)).save_city(message.from_user.id, city)
    await _finish_profile_setup(message, state, session)


@router.callback_query(F.data == "buy_sticker")
async def buy_sticker(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    promo_id = data.get("promotion_id")
    promo = await PromotionRepository(session).get(promo_id) if promo_id else await _active_promotion(session)

    if not promo:
        await callback.answer("Акция не найдена.", show_alert=True)
        return

    methods = await PromotionQRRepository(session).list_for_promo(promo.id)
    if not methods:
        await callback.answer("Для этой акции пока не добавлены способы оплаты.", show_alert=True)
        return

    await state.update_data(
        promotion_id=promo.id,
        purchase_count=None,
        purchase_total=None,
        qr_id=None,
    )
    buttons = await StickerButtonRepository(session).list_for_promo(promo.id)
    stickers_text = await _get_stickers_text(session)
    await _answer_car(
        callback,
        stickers_text,
        sticker_buttons_kb(buttons) if buttons else sticker_count_kb(),
        promo,
    )

@router.callback_query(F.data.startswith("qr_select:"))
async def qr_selected(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    qr_id = int(callback.data.split(":", 1)[1])
    await state.update_data(qr_id=qr_id)
    data = await state.get_data()
    promo_id = data.get("promotion_id")
    promo = await PromotionRepository(session).get(promo_id) if promo_id else await _active_promotion(session)

    if not promo:
        await callback.answer("Акция не найдена.", show_alert=True)
        return

    count = data.get("purchase_count")
    total = data.get("purchase_total")
    if not count or not total:
        buttons = await StickerButtonRepository(session).list_for_promo(promo.id)
        stickers_text = await _get_stickers_text(session)
        await _answer_car(
            callback,
            stickers_text,
            sticker_buttons_kb(buttons) if buttons else sticker_count_kb(),
            promo,
        )
        return

    method = await PromotionQRRepository(session).get(qr_id)
    if not method or method.promotion_id != promo.id:
        await callback.answer("Способ оплаты не найден.", show_alert=True)
        return
    await _show_payment_method(callback.message, session, promo, method, int(count), str(total))
    await callback.answer()


@router.callback_query(F.data == "change_full_name")
async def change_full_name(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(profile_edit_only=True)
    await state.set_state(GiveawayStates.waiting_full_name)
    await callback.message.answer("Введите ваши ФИО полностью:", reply_markup=remove_reply_kb())
    await callback.answer()


@router.callback_query(F.data == "change_city")
async def change_city(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(profile_edit_only=True)
    await state.set_state(GiveawayStates.waiting_city)
    await callback.message.answer("Введите ваш город:", reply_markup=remove_reply_kb())
    await callback.answer()


async def _finish_profile_setup(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    if data.get("profile_edit_only"):
        await state.clear()
        user = await UserRepository(session).get_by_telegram_id(message.from_user.id)
        await message.answer(
            "✅ Данные сохранены.\n\n"
            f"ФИО: <b>{escape(user.customer_full_name or 'не указано')}</b>\n"
            f"Город: <b>{escape(user.city or 'не указан')}</b>\n"
            f"Телефон: <code>{user.phone_number or 'не указан'}</code>",
            reply_markup=my_phone_kb(),
            parse_mode="HTML",
        )
        return
    promo_id = data.get("promotion_id")
    promo = await PromotionRepository(session).get(promo_id) if promo_id else await _active_promotion(session)
    await state.clear()
    await _send_car(message, await _saved_phone_text(promo, session), buy_sticker_with_phone_kb(), promo)

@router.callback_query(F.data.startswith("stickers_btn:"))
async def stickers_btn_press(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    btn_id = int(callback.data.split(":", 1)[1])
    btn = await StickerButtonRepository(session).get(btn_id)
    if not btn:
        await callback.answer("Кнопка не найдена.", show_alert=True)
        return

    data = await state.get_data()
    promo_id = data.get("promotion_id")
    promo = await PromotionRepository(session).get(promo_id) if promo_id else await _active_promotion(session)
    if not promo:
        await callback.answer("Акция не найдена.", show_alert=True)
        return
    await _continue_purchase(callback.message, state, session, promo, btn.sticker_count)
    await callback.answer()

@router.callback_query(F.data == "stickers_custom")
async def stickers_custom_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(GiveawayStates.waiting_custom_sticker_count)
    await callback.message.answer(
        "Введите количество стикеров которое хотите купить:",
        reply_markup=remove_reply_kb(),
    )
    await callback.answer()


@router.message(GiveawayStates.waiting_custom_sticker_count)
async def stickers_custom_count(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        count = int((message.text or "").strip())
        if count <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите целое положительное число. Например: 7")
        return

    data = await state.get_data()
    promo_id = data.get("promotion_id")
    promo = await PromotionRepository(session).get(promo_id) if promo_id else await _active_promotion(session)
    if not promo:
        await state.clear()
        await message.answer("Акция не найдена.")
        return
    await _continue_purchase(message, state, session, promo, count)

@router.callback_query(F.data.startswith("stickers:"))
async def choose_sticker_count(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    count = int(callback.data.split(":", 1)[1])
    data = await state.get_data()

    promo_id = data.get("promotion_id")
    promo = await PromotionRepository(session).get(promo_id) if promo_id else await _active_promotion(session)
    if not promo:
        await callback.answer("Акция не найдена.", show_alert=True)
        return
    await _continue_purchase(callback.message, state, session, promo, count)
    await callback.answer()


@router.callback_query(F.data == "how_to_pay")
async def how_to_pay(callback: CallbackQuery, session: AsyncSession) -> None:
    custom_text = await SettingsRepository(session).get("post_how_to_pay_text", "")
    if not custom_text:
        custom_text = await SettingsRepository(session).get(PAYMENT_INSTRUCTION_TEXT_KEY, "")
    text = custom_text or HOW_TO_PAY_TEXT.replace(
        f"@{settings.payment_manager_username}",
        f"@{await _payment_manager_username(session)}",
    )
    await callback.message.answer(text, reply_markup=back_kb("buy_sticker"))
    await callback.answer()


@router.callback_query(F.data == "where_number")
async def where_number(callback: CallbackQuery, session: AsyncSession) -> None:
    text = await SettingsRepository(session).get(
        "post_where_number_text",
        "Ответ может занимать до 24 часов. Не пишите новые сообщения менеджеру до истечения этого времени.",
    )
    await callback.message.answer(text, reply_markup=back_kb("buy_sticker"))
    await callback.answer()
