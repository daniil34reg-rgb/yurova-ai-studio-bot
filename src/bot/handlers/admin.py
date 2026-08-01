import re
from datetime import datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.content import DEFAULT_BANK_CHOICE_TEXT, build_default_payment_instruction
from bot.keyboards import (
    back_kb,
    admin_cancel_kb,
    admin_bank_choice_text_kb,
    admin_panel_kb,
    admin_payment_kb,
    admin_payment_instruction_kb,
    admin_payment_manager_kb,
    admin_promotion_edit_kb,
    admin_promotions_kb,
    admin_stickers_text_kb,
    admin_button_config_apply_list_kb,
    admin_button_config_button_edit_kb,
    admin_button_config_detail_kb,
    admin_button_configs_kb,
    admin_skip_photo_kb,
    admin_qr_list_kb,
    admin_saved_qr_apply_list_kb,
    admin_saved_qr_detail_kb,
    admin_saved_qr_list_kb,
)
from bot.keyboards.keyboards import admin_back_kb, admin_sticker_buttons_kb, admin_btn_edit_kb, admin_help_choice_kb, \
    admin_payment_text_kb, admin_promo_back_kb, admin_content_kb, admin_payment_settings_kb, \
    admin_users_kb, admin_payment_method_type_kb, admin_payment_method_detail_kb, \
    admin_post_payment_settings_kb, admin_post_payment_item_kb, admin_qr_delete_all_confirm_kb
from bot.logging_setup.logger import logger
from bot.models import PaymentStatus
from bot.repositories import (
    AccessRepository,
    PaymentRepository,
    PromotionQRRepository,
    PromotionRepository,
    SavedQRRepository,
    SavedStickerButtonConfigRepository,
    SettingsRepository,
    StickerButtonRepository,
    UserRepository,
    SentQRMessageRepository,
)
from bot.services import (
    AccessService,
    AdminService,
    PaymentService,
    UserService,
    build_participants_csv,
    get_qr_auto_delete_hours,
)
from bot.services.qr_cleanup_service import MAX_QR_AUTO_DELETE_HOURS, QR_AUTO_DELETE_HOURS_KEY
from bot.states import AdminStates

router = Router()
MAIN_MENU_PHOTO_KEY = "main_menu_photo_file_id"
PAYMENT_INSTRUCTION_TEXT_KEY = "payment_instruction_text"
BANK_CHOICE_TEXT_KEY = "bank_choice_text"
STICKERS_TEXT_KEY = "stickers_text"
PAYMENT_MANAGER_USERNAME_KEY = "payment_manager_username"
MAIN_JOIN_BUTTON_LABEL_KEY = "main_join_button_label"
WARNING_TEXT_KEY = "warning_text"
POST_PAYMENT_DEFAULTS = {
    "send_receipt": "🧾 ОТПРАВИТЬ ЧЕК МЕНЕДЖЕРУ ↗",
    "buy_again": "Купить ещё",
    "how_to_pay": "Как оплатить ❓",
    "where_number": "Где мой номер?",
}
DEFAULT_PURCHASE_BUTTONS = (
    ("1 стикер", 1, 1),
    ("2 стикера", 2, 1),
    ("3 стикера", 3, 1),
    ("5 стикеров + 1 в подарок", 5, 2),
    ("10 стикеров + 2 в подарок", 10, 2),
)


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


async def _main_menu_photo_exists(session: AsyncSession) -> bool:
    return bool(await SettingsRepository(session).get(MAIN_MENU_PHOTO_KEY, ""))


async def _admin_panel_kb(session: AsyncSession):
    return admin_panel_kb(await _main_menu_photo_exists(session))


def _normalize_telegram_username(raw: str) -> str | None:
    value = raw.strip()
    value = re.sub(r"^https?://t\.me/", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^t\.me/", "", value, flags=re.IGNORECASE)
    value = value.lstrip("@").split("/", 1)[0].split("?", 1)[0].strip()
    if re.fullmatch(r"[A-Za-z0-9_]{5,32}", value):
        return value
    return None


def _promo_text(promo, qr_count: int = 0, button_count: int | None = None) -> str:
    active = "Да" if promo.is_active else "Нет"
    photo = "Да" if promo.photo_file_id else "Нет"
    return (
        f"<b>Акция #{promo.id}</b>\n\n"
        f"Название в админке: <b>{escape(promo.title)}</b>\n"
        f"Название для пользователей: <b>{escape(promo.prize_name)}</b>\n"
        f"Цена за 1 стикер: <b>{promo.price_per_sticker:.2f} ₽</b>\n"
        f"Активная: <b>{active}</b>\n"
        f"Фото акции: <b>{photo}</b>\n"
        f"Способов оплаты: <b>{qr_count}</b>\n"
        + (
            f"Вариантов покупки: <b>{button_count}</b>\n"
            f"Готовность: <b>{'✅ можно публиковать' if qr_count and button_count else '⚠️ настройка не завершена'}</b>"
            if button_count is not None
            else ""
        )
    )


async def _open_admin_panel(message: Message, session: AsyncSession) -> None:
    await message.answer(
        "🔐 <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=await _admin_panel_kb(session),
        parse_mode="HTML",
    )


async def _show_promo(message: Message, session: AsyncSession, promo) -> None:
    if not promo:
        await message.answer("Акция не найдена.", reply_markup=await _admin_panel_kb(session))
        return
    qr_count = await PromotionQRRepository(session).count_for_promo(promo.id)
    button_count = len(await StickerButtonRepository(session).list_for_promo(promo.id))
    await message.answer(
        "✅ Изменения сохранены.\n\n" + _promo_text(promo, qr_count, button_count),
        reply_markup=admin_promotion_edit_kb(promo.id, promo.is_active),
        parse_mode="HTML",
    )


def _button_config_text(config) -> str:
    lines = [
        f"🧩 <b>Шаблон вариантов покупки #{config.id}</b>",
        "",
        f"Название: <b>{escape(config.title)}</b>",
        f"Кнопок: <b>{len(config.buttons)}</b>",
    ]
    if config.buttons:
        lines.append("")
        lines.extend(
            f"{index}. {escape(btn.label)} — <b>{btn.sticker_count} шт.</b>, {_sticker_button_width_text(getattr(btn, 'row_width', 1))}"
            for index, btn in enumerate(config.buttons, start=1)
        )
    return "\n".join(lines)


def _sticker_button_width_text(row_width: int) -> str:
    return "широкая, на всю строку" if row_width == 2 else "обычная, по две в строке"


async def _show_button_config(message: Message, session: AsyncSession, config_id: int, prefix: str = "") -> None:
    config = await SavedStickerButtonConfigRepository(session).get(config_id)
    if not config:
        await message.answer("Шаблон вариантов покупки не найден.", reply_markup=await _admin_panel_kb(session))
        return
    await message.answer(
        prefix + _button_config_text(config),
        reply_markup=admin_button_config_detail_kb(config.id, config.buttons),
        parse_mode="HTML",
    )


@router.message(Command("admin"))
async def admin_panel(message: Message, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    await _open_admin_panel(message, session)


@router.callback_query(F.data == "admin_open")
async def admin_open(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.clear()
    await _open_admin_panel(callback.message, session)
    await callback.answer()


@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text(
        "🔐 <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=await _admin_panel_kb(session),
        parse_mode="HTML",
    )
    await callback.answer()

@router.callback_query(F.data == "admin_help")
async def admin_help(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text(
        "❓ <b>Справка</b>\n\nВыберите раздел:",
        reply_markup=admin_help_choice_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_content")
async def admin_content(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text(
        "🖼 <b>Главное меню</b>\n\n"
        "Здесь настраивается первый экран после /start: приветствие, фото, "
        "название кнопки участия и предупреждение о сторонних ссылках.",
        reply_markup=admin_content_kb(await _main_menu_photo_exists(session)),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_payment_settings")
async def admin_payment_settings(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text(
        "💳 <b>Тексты и контакты оплаты</b>\n\n"
        "Здесь нет банков и QR-кодов. Здесь настраиваются только общая инструкция, "
        "текст выбора способа, контакт менеджера, кнопки после оплаты и автоудаление QR.\n\n"
        "Банки, QR-коды и ссылки добавляются отдельно внутри каждой акции.",
        reply_markup=admin_payment_settings_kb(await get_qr_auto_delete_hours(session)),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_qr_auto_delete")
async def admin_qr_auto_delete_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not is_admin(callback.from_user.id):
        return
    current = await get_qr_auto_delete_hours(session)
    current_text = "выключено" if current == 0 else f"{current} ч"
    await state.set_state(AdminStates.waiting_qr_auto_delete_hours)
    await callback.message.edit_text(
        "🕒 <b>Автоудаление QR-кодов</b>\n\n"
        f"Сейчас: <b>{current_text}</b>.\n\n"
        "После выбранного срока бот удалит отправленное сообщение с QR-кодом "
        "из чата каждого пользователя. Настройка применяется ко всем акциям.\n\n"
        f"Отправьте целое число от <b>1</b> до <b>{MAX_QR_AUTO_DELETE_HOURS}</b> — срок в часах. "
        "Отправьте <b>0</b>, чтобы выключить автоудаление и отменить уже запланированные удаления.\n\n"
        "Telegram разрешает ботам удалять такие сообщения только в течение 48 часов, поэтому максимум — 47.",
        reply_markup=back_kb("admin_payment_settings"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_qr_auto_delete_hours)
async def admin_qr_auto_delete_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not is_admin(message.from_user.id):
        return
    raw_value = (message.text or "").strip()
    try:
        hours = int(raw_value)
    except ValueError:
        hours = -1
    if hours != 0 and not 1 <= hours <= MAX_QR_AUTO_DELETE_HOURS:
        await message.answer(
            f"Введите целое число от 1 до {MAX_QR_AUTO_DELETE_HOURS}, либо 0 для отключения.",
            reply_markup=back_kb("admin_payment_settings"),
        )
        return

    await SettingsRepository(session).set(QR_AUTO_DELETE_HOURS_KEY, str(hours))
    cancelled = 0
    if hours == 0:
        cancelled = await SentQRMessageRepository(session).delete_all()
    await state.clear()
    if hours == 0:
        result_text = f"✅ Автоудаление QR выключено. Отменено запланированных удалений: {cancelled}."
    else:
        result_text = f"✅ QR-коды будут автоматически удаляться через {hours} ч после отправки."
    await message.answer(
        result_text,
        reply_markup=admin_payment_settings_kb(hours),
    )


@router.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text(
        "👥 <b>Пользователи</b>\n\nВыберите действие:",
        reply_markup=admin_users_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_help_main")
async def admin_help_main(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    text = (
        "❓ <b>Справка — Главная панель</b>\n\n"
        "<b>🎁 Акции</b> — всё, что относится к конкретной акции: цена, "
        "варианты покупки, банки, QR и ссылки.\n\n"
        "<b>🧩 Шаблоны вариантов покупки</b> — сохранённые наборы кнопок, "
        "которые можно применять к разным акциям.\n\n"
        "<b>📷 Библиотека QR-кодов</b> — сохраните QR один раз, затем включайте "
        "один, два или несколько QR в каждой акции.\n\n"
        "<b>📝 Тексты и контакты оплаты</b> — общая инструкция, текст выбора "
        "банка и Telegram менеджера для чеков.\n\n"
        "<b>🖼 Главное меню</b> — приветствие и фото первого экрана.\n\n"
        "<b>👥 Пользователи</b> — статистика, рассылка и бан/разбан.\n\n"
        "Рекомендуемый порядок настройки: создайте QR в библиотеке → создайте "
        "акцию → проверьте варианты покупки → добавьте нужные банки и QR → "
        "опубликуйте акцию."
    )
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_help_promo")
async def admin_help_promo(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    text = (
        "❓ <b>Справка — Настройки акции</b>\n\n"

        "<b>Сделать активной / Деактивировать</b>\n"
        "Включить или выключить акцию. Только активные акции видят пользователи в главном меню.\n\n"

        "<b>Управление QR кодами</b>\n"
        "Банки и способы оплаты только для этой акции.\n"
        "• Можно добавить один, два или несколько QR-кодов и ссылок\n"
        "• Название банка, QR и ссылку можно менять после создания\n"
        "• Можно последовательно включить несколько QR из общей библиотеки\n"
        "• Если способ один — он откроется сразу после выбора количества\n"
        "• Если способов несколько — пользователь выберет банк после количества\n\n"

        "<b>Кнопки стикеров</b>\n"
        "Варианты покупки, которые пользователь выбирает перед банком.\n"
        "• Каждая кнопка имеет текст и количество стикеров\n"
        "• Текст может быть «5 + 1 в подарок», а оплачиваемое количество — 5\n"
        "• Цена считается автоматически: кол-во × цена за 1 стикер акции\n"
        "• Всегда есть кнопка «Другое кол-во» — пользователь вводит число вручную\n"
        "• Новая акция получает стандартные кнопки 1 / 2 / 3 / 5+1 / 10+2\n"
        "• Можно менять текст, количество, порядок, ширину или применить шаблон\n\n"

        "<b>Изменить описание</b>\n"
        "Текст на странице после ввода номера телефона.\n"
        "Это то что пользователь видит перед кнопкой «Купить стикер».\n\n"

        "<b>Изменить текст оплаты</b>\n"
        "Текст под QR-кодом на странице оплаты.\n"
        "Поддерживает переменную <code>{price}</code> — подставляет цену за 1 стикер"
        "Если не задан — используется общий текст из настроек панели.\n"
        "А так же переменную <code>{total}</code> — показывает итоговую сумму к оплате.\n\n"

        "<b>Изменить название</b>\n"
        "Внутреннее название акции — видно только в админке.\n\n"

        "<b>Название для пользователей</b>\n"
        "Это название акции видно пользователям в главном меню и при выборе акции. "
        "Призы и их количество указываются в описании акции.\n\n"

        "<b>Изменить фото</b>\n"
        "Главное фото акции — на странице выбора банка.\n\n"

        "<b>Изменить цену</b>\n"
        "Цена за 1 стикер в рублях. От неё считается итоговая сумма для всех кнопок.\n\n"

        "<b>Удалить</b>\n"
        "Полностью удаляет акцию вместе со всеми QR-кодами и кнопками стикеров."
    )
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_main_menu_photo_add")
async def admin_main_menu_photo_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await state.set_state(AdminStates.waiting_main_menu_photo)
    await callback.message.edit_text(
        "Отправьте фото, которое нужно показывать в главном меню.",
        reply_markup=admin_cancel_kb(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_main_menu_photo)
async def admin_main_menu_photo_save(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.photo:
        await message.answer("Пожалуйста, отправьте именно фото.", reply_markup=admin_cancel_kb())
        return
    await SettingsRepository(session).set(MAIN_MENU_PHOTO_KEY, message.photo[-1].file_id)
    await state.clear()
    await message.answer(
        "✅ Фото главного меню сохранено.",
        reply_markup=admin_panel_kb(main_menu_photo_exists=True),
    )


@router.callback_query(F.data == "admin_main_menu_photo_delete")
async def admin_main_menu_photo_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    await SettingsRepository(session).set(MAIN_MENU_PHOTO_KEY, "")
    await callback.message.edit_text(
        "🗑 Фото главного меню удалено.",
        reply_markup=admin_panel_kb(main_menu_photo_exists=False),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_promos")
async def admin_promos(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    promos = await PromotionRepository(session).list_all()
    text = "🎁 <b>Акции</b>\n\nВыберите акцию для управления." if promos else "🎁 <b>Акции</b>\n\nАкций пока нет."
    await callback.message.edit_text(text, reply_markup=admin_promotions_kb(promos), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_promo:"))
async def admin_promo_show(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    promo_id = int(callback.data.split(":", 1)[1])
    promo = await PromotionRepository(session).get(promo_id)
    if not promo:
        await callback.answer("Акция не найдена", show_alert=True)
        return
    qr_count = await PromotionQRRepository(session).count_for_promo(promo_id)
    button_count = len(await StickerButtonRepository(session).list_for_promo(promo_id))
    await callback.message.edit_text(
        _promo_text(promo, qr_count, button_count),
        reply_markup=admin_promotion_edit_kb(promo.id, promo.is_active),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Создание акции ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_promo_add")
async def admin_promo_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await state.set_state(AdminStates.waiting_promo_title)
    await callback.message.edit_text(
        "Введите название акции в админке.\n\n<b>Его увидите только вы.</b>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_promo_title)
async def admin_promo_title(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer("Название слишком короткое. Введите название акции.")
        return
    await state.update_data(promo_title=title)
    await state.set_state(AdminStates.waiting_promo_prize)
    await message.answer(
        "Введите название акции для пользователей.\n\n"
        "<b>Его пользователь увидит в главном меню и при выборе акции.</b>\n"
        "Призы и их количество позже укажите в описании акции.",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_promo_prize)
async def admin_promo_prize(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    prize = (message.text or "").strip()
    if len(prize) < 2:
        await message.answer("Название слишком короткое. Введите название акции для пользователей.")
        return
    await state.update_data(promo_prize=prize)
    await state.set_state(AdminStates.waiting_promo_price)
    await message.answer(
        "Введите цену за 1 единицу товара в рублях.",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_promo_price)
async def admin_promo_price(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        price = float((message.text or "").strip().replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректную цену. Например: 1999.9")
        return
    await state.update_data(promo_price=price)
    await state.set_state(AdminStates.waiting_promo_photo)
    await message.answer(
        "Отправьте фото акции (главное фото) или нажмите «Пропустить фото».",
        reply_markup=admin_skip_photo_kb(),
    )


@router.message(AdminStates.waiting_promo_photo)
async def admin_promo_photo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.photo:
        await message.answer("Нужно отправить фото или нажать «Пропустить фото».", reply_markup=admin_skip_photo_kb())
        return
    await _create_promo_from_state(message, state, session, message.photo[-1].file_id)


@router.callback_query(F.data == "admin_promo_skip_photo")
async def admin_promo_skip_photo(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    msg = callback.message
    await _create_promo_from_state(msg, state, session, None)
    await callback.answer()


async def _create_promo_from_state(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    photo_file_id: str | None,
) -> None:
    data = await state.get_data()
    title = data.get("promo_title")
    prize = data.get("promo_prize")
    price = float(data.get("promo_price", 1999.9))
    if not title or not prize:
        await state.clear()
        await message.answer(
            "Данные акции потерялись. Начните заново через /admin.",
            reply_markup=await _admin_panel_kb(session),
        )
        return
    promo = await PromotionRepository(session).create(title, prize, price, photo_file_id)
    button_repo = StickerButtonRepository(session)
    for label, count, row_width in DEFAULT_PURCHASE_BUTTONS:
        await button_repo.add(promo.id, label, count, row_width)
    await state.clear()
    await message.answer(
        (
            "✅ Акция создана.\n\n"
            "Стандартные варианты покупки уже добавлены: 1 / 2 / 3 / 5+1 / 10+2. "
            "Их названия и количество можно изменить в разделе «Варианты покупки».\n\n"
            "Теперь добавьте нужные банки, QR-коды или ссылки на оплату.\n\n"
            f"{_promo_text(promo, 0)}"
        ),
        reply_markup=admin_promotion_edit_kb(promo.id, promo.is_active),
        parse_mode="HTML",
    )


# ── Управление QR кодами ──────────────────────────────────────────────────────


def _saved_qr_text(qr) -> str:
    return (
        f"<b>QR-код #{qr.id}</b>\n\n"
        f"Название: <b>{escape(qr.title)}</b>\n"
        "Фото QR: <b>Да</b>\n\n"
        "После добавления в акцию это название пользователь увидит "
        "на кнопке выбора оплаты."
    )


async def _show_saved_qr(message: Message, qr) -> None:
    if not qr:
        await message.answer("QR-код не найден.", reply_markup=admin_panel_kb())
        return
    await message.answer_photo(
        photo=qr.file_id,
        caption=_saved_qr_text(qr),
        reply_markup=admin_saved_qr_detail_kb(qr.id),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_saved_qrs")
async def admin_saved_qrs(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    qr_codes = await SavedQRRepository(session).list_all()
    text = "📂 <b>QR-коды</b>\n\nВыберите QR для просмотра и изменения." if qr_codes else "📂 <b>QR-коды</b>\n\nСохранённых QR пока нет."
    if callback.message.photo:
        await callback.message.answer(text, reply_markup=admin_saved_qr_list_kb(qr_codes), parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=admin_saved_qr_list_kb(qr_codes), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_saved_qr_add")
async def admin_saved_qr_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await state.set_state(AdminStates.waiting_saved_qr_title)
    await callback.message.edit_text(
        "Введите название банка или способа оплаты для пользователя.\n\n"
        "<b>Пользователь увидит этот текст на кнопке выбора оплаты.</b>\n"
        "Например: <b>Альфа-Банк</b> или <b>Т-Банк</b>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_saved_qr_title)
async def admin_saved_qr_title(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer("Название слишком короткое.")
        return
    await state.update_data(saved_qr_title=title)
    await state.set_state(AdminStates.waiting_saved_qr_photo)
    await message.answer(
        f"📷 Отправьте фото QR-кода для <b>{escape(title)}</b>:",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_saved_qr_photo)
async def admin_saved_qr_photo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.photo:
        await message.answer("Нужно отправить фото QR-кода.", reply_markup=admin_cancel_kb())
        return
    data = await state.get_data()
    title = data.get("saved_qr_title")
    if not title:
        await state.clear()
        await message.answer("Данные QR потерялись. Начните заново через /admin.", reply_markup=await _admin_panel_kb(session))
        return
    qr = await SavedQRRepository(session).create(title, message.photo[-1].file_id)
    await state.clear()
    await message.answer("✅ QR-код сохранён в библиотеку.")
    await _show_saved_qr(message, qr)


@router.callback_query(F.data.startswith("admin_saved_qr:"))
async def admin_saved_qr_show(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    qr_id = int(callback.data.split(":", 1)[1])
    qr = await SavedQRRepository(session).get(qr_id)
    if not qr:
        await callback.answer("QR-код не найден.", show_alert=True)
        return
    await callback.message.answer_photo(
        photo=qr.file_id,
        caption=_saved_qr_text(qr),
        reply_markup=admin_saved_qr_detail_kb(qr.id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_saved_qr_edit_title:"))
async def admin_saved_qr_edit_title_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    qr_id = int(callback.data.split(":", 1)[1])
    await state.set_state(AdminStates.waiting_edit_saved_qr_title)
    await state.update_data(edit_saved_qr_id=qr_id)
    await callback.message.answer("Введите новое название QR-кода:", reply_markup=admin_cancel_kb())
    await callback.answer()


@router.message(AdminStates.waiting_edit_saved_qr_title)
async def admin_saved_qr_edit_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer("Название слишком короткое. Попробуйте еще раз.")
        return
    data = await state.get_data()
    qr = await SavedQRRepository(session).update_title(int(data["edit_saved_qr_id"]), title)
    await state.clear()
    await message.answer("✅ Название QR-кода обновлено.")
    await _show_saved_qr(message, qr)


@router.callback_query(F.data.startswith("admin_saved_qr_edit_photo:"))
async def admin_saved_qr_edit_photo_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    qr_id = int(callback.data.split(":", 1)[1])
    await state.set_state(AdminStates.waiting_edit_saved_qr_photo)
    await state.update_data(edit_saved_qr_id=qr_id)
    await callback.message.answer("Отправьте новое фото QR-кода:", reply_markup=admin_cancel_kb())
    await callback.answer()


@router.message(AdminStates.waiting_edit_saved_qr_photo)
async def admin_saved_qr_edit_photo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.photo:
        await message.answer("Пожалуйста, отправьте именно фото.", reply_markup=admin_cancel_kb())
        return
    data = await state.get_data()
    qr = await SavedQRRepository(session).update_photo(int(data["edit_saved_qr_id"]), message.photo[-1].file_id)
    await state.clear()
    await message.answer("✅ Фото QR-кода обновлено.")
    await _show_saved_qr(message, qr)


@router.callback_query(F.data.startswith("admin_saved_qr_delete:"))
async def admin_saved_qr_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    qr_id = int(callback.data.split(":", 1)[1])
    deleted = await SavedQRRepository(session).delete(qr_id)
    qr_codes = await SavedQRRepository(session).list_all()
    text = "🗑 QR-код удалён.\n\nВыберите следующий QR." if deleted else "QR-код не найден."
    await callback.message.answer(text, reply_markup=admin_saved_qr_list_kb(qr_codes))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_promo_qr_list:"))
async def admin_qr_list(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":", 1)[1])
    qr_codes = await PromotionQRRepository(session).list_for_promo(promo_id)
    text = (
        f"🏦 <b>Банки и способы оплаты акции #{promo_id}</b>\n\n"
        "Каждая строка ниже — отдельная кнопка, которую увидит покупатель "
        "после выбора количества. Можно оставить один, два, три и больше способов.\n\n"
    )
    if qr_codes:
        text += "\n".join(
            f"• {'🔗' if getattr(method, 'method_type', 'qr') == 'link' else '📷'} {method.title}"
            for method in qr_codes
        )
    else:
        text += "Способов оплаты пока нет."
    await callback.message.edit_text(
        text,
        reply_markup=admin_qr_list_kb(promo_id, qr_codes),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_qr_add:"))
async def admin_qr_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":", 1)[1])
    await state.update_data(qr_promo_id=promo_id)
    await state.set_state(AdminStates.waiting_qr_title)
    await callback.message.answer(
        "Введите название банка или способа оплаты для пользователя.\n\n"
        "<b>Пользователь увидит этот текст на кнопке выбора оплаты.</b>\n"
        "Например: <b>Альфа-Банк</b> или <b>Т-Банк</b>",
        reply_markup=admin_promo_back_kb(promo_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_payment_method_add:"))
async def admin_payment_method_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.rsplit(":", 1)[1])
    await state.clear()
    await callback.message.edit_text(
        "➕ <b>Новый способ оплаты</b>\n\n"
        "Выберите, что увидит пользователь: изображение QR-кода или кнопку со ссылкой.",
        reply_markup=admin_payment_method_type_kb(promo_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_payment_method_type:"))
async def admin_payment_method_type(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, method_type, promo_id_raw = callback.data.split(":")
    promo_id = int(promo_id_raw)
    await state.update_data(payment_method_type=method_type, qr_promo_id=promo_id)
    await state.set_state(AdminStates.waiting_payment_method_title)
    await callback.message.answer(
        "Введите название банка или способа оплаты для пользователя.\n\n"
        "<b>Пользователь увидит этот текст на кнопке выбора оплаты.</b>\n"
        "Например: <b>СБП — Альфа-Банк</b> или <b>Оплата на сайте</b>.",
        reply_markup=admin_promo_back_kb(promo_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_payment_method_title)
async def admin_payment_method_title(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer("Название должно содержать хотя бы 2 символа.")
        return
    data = await state.get_data()
    await state.update_data(qr_title=title)
    if data.get("payment_method_type") == "link":
        await state.set_state(AdminStates.waiting_payment_method_link)
        await message.answer(
            "Отправьте полную ссылку на страницу оплаты, начиная с <code>https://</code>.",
            reply_markup=admin_promo_back_kb(data["qr_promo_id"]),
            parse_mode="HTML",
        )
    else:
        await state.set_state(AdminStates.waiting_qr_photo)
        await message.answer(
            f"Отправьте изображение QR-кода для <b>{escape(title)}</b>.",
            reply_markup=admin_promo_back_kb(data["qr_promo_id"]),
            parse_mode="HTML",
        )


@router.message(AdminStates.waiting_payment_method_link)
async def admin_payment_method_link(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if not is_admin(message.from_user.id):
        return
    payment_url = (message.text or "").strip()
    if not re.fullmatch(r"https://[^\s]{3,}", payment_url, flags=re.IGNORECASE):
        await message.answer("Нужна корректная безопасная ссылка, начинающаяся с https://")
        return
    data = await state.get_data()
    promo_id = int(data["qr_promo_id"])
    await PromotionQRRepository(session).add_link(promo_id, data["qr_title"], payment_url)
    methods = await PromotionQRRepository(session).list_for_promo(promo_id)
    await state.clear()
    await message.answer(
        "✅ Ссылка на оплату добавлена.",
        reply_markup=admin_qr_list_kb(promo_id, methods),
    )


@router.callback_query(F.data.startswith("admin_payment_method:"))
async def admin_payment_method_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, method_id_raw, promo_id_raw = callback.data.split(":")
    method_id = int(method_id_raw)
    promo_id = int(promo_id_raw)
    method = await PromotionQRRepository(session).get(method_id)
    if not method:
        await callback.answer("Способ оплаты не найден.", show_alert=True)
        return
    kind = "Ссылка" if getattr(method, "method_type", "qr") == "link" else "QR-код"
    text = (
        f"💳 <b>{escape(method.title)}</b>\n\n"
        f"Тип: <b>{kind}</b>\n"
        f"Акция: <b>#{promo_id}</b>"
    )
    if getattr(method, "payment_url", None):
        text += f"\nСсылка: {escape(method.payment_url)}"
    await callback.message.answer(
        text,
        reply_markup=admin_payment_method_detail_kb(
            method_id,
            promo_id,
            getattr(method, "method_type", "qr"),
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_payment_method_edit_title:"))
async def admin_payment_method_edit_title_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, method_id_raw, promo_id_raw = callback.data.split(":")
    method_id = int(method_id_raw)
    promo_id = int(promo_id_raw)
    method = await PromotionQRRepository(session).get(method_id)
    if not method or method.promotion_id != promo_id:
        await callback.answer("Способ оплаты не найден.", show_alert=True)
        return
    await state.update_data(payment_method_id=method_id, payment_method_promo_id=promo_id)
    await state.set_state(AdminStates.waiting_edit_payment_method_title)
    await callback.message.answer(
        f"Текущее название: <b>{escape(method.title)}</b>\n\n"
        "Введите новое название банка или способа оплаты.\n"
        "<b>Пользователь увидит его на кнопке выбора оплаты.</b>",
        reply_markup=admin_promo_back_kb(promo_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_edit_payment_method_title)
async def admin_payment_method_edit_title_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not is_admin(message.from_user.id):
        return
    title = (message.text or "").strip()
    if len(title) < 2 or len(title) > 64:
        await message.answer("Название должно содержать от 2 до 64 символов.")
        return
    data = await state.get_data()
    method_id = int(data["payment_method_id"])
    promo_id = int(data["payment_method_promo_id"])
    method = await PromotionQRRepository(session).get(method_id)
    if not method or method.promotion_id != promo_id:
        await state.clear()
        await message.answer("Способ оплаты не найден.")
        return
    await PromotionQRRepository(session).update_title(method_id, title)
    methods = await PromotionQRRepository(session).list_for_promo(promo_id)
    await state.clear()
    await message.answer(
        "✅ Название кнопки оплаты изменено.",
        reply_markup=admin_qr_list_kb(promo_id, methods),
    )


@router.callback_query(F.data.startswith("admin_payment_method_edit_content:"))
async def admin_payment_method_edit_content_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, method_id_raw, promo_id_raw = callback.data.split(":")
    method_id = int(method_id_raw)
    promo_id = int(promo_id_raw)
    method = await PromotionQRRepository(session).get(method_id)
    if not method or method.promotion_id != promo_id:
        await callback.answer("Способ оплаты не найден.", show_alert=True)
        return
    await state.update_data(payment_method_id=method_id, payment_method_promo_id=promo_id)
    if getattr(method, "method_type", "qr") == "link":
        await state.set_state(AdminStates.waiting_edit_payment_method_link)
        text = "Отправьте новую ссылку на оплату, начинающуюся с <code>https://</code>."
    else:
        await state.set_state(AdminStates.waiting_edit_payment_method_qr)
        text = "Отправьте новое изображение QR-кода."
    await callback.message.answer(
        text,
        reply_markup=admin_promo_back_kb(promo_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_edit_payment_method_link)
async def admin_payment_method_edit_link_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not is_admin(message.from_user.id):
        return
    payment_url = (message.text or "").strip()
    if not re.fullmatch(r"https://[^\s]{3,}", payment_url, flags=re.IGNORECASE):
        await message.answer("Нужна корректная безопасная ссылка, начинающаяся с https://")
        return
    data = await state.get_data()
    method_id = int(data["payment_method_id"])
    promo_id = int(data["payment_method_promo_id"])
    method = await PromotionQRRepository(session).get(method_id)
    if not method or method.promotion_id != promo_id:
        await state.clear()
        await message.answer("Способ оплаты не найден.")
        return
    await PromotionQRRepository(session).update_link(method_id, payment_url)
    methods = await PromotionQRRepository(session).list_for_promo(promo_id)
    await state.clear()
    await message.answer(
        "✅ Ссылка на оплату изменена.",
        reply_markup=admin_qr_list_kb(promo_id, methods),
    )


@router.message(AdminStates.waiting_edit_payment_method_qr)
async def admin_payment_method_edit_qr_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.photo:
        await message.answer("Нужно отправить изображение QR-кода.")
        return
    data = await state.get_data()
    method_id = int(data["payment_method_id"])
    promo_id = int(data["payment_method_promo_id"])
    method = await PromotionQRRepository(session).get(method_id)
    if not method or method.promotion_id != promo_id:
        await state.clear()
        await message.answer("Способ оплаты не найден.")
        return
    await PromotionQRRepository(session).update_qr(method_id, message.photo[-1].file_id)
    methods = await PromotionQRRepository(session).list_for_promo(promo_id)
    await state.clear()
    await message.answer(
        "✅ QR-код заменён.",
        reply_markup=admin_qr_list_kb(promo_id, methods),
    )


@router.message(AdminStates.waiting_qr_title)
async def admin_qr_title(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer("Название слишком короткое.")
        return
    await state.update_data(qr_title=title)
    await state.set_state(AdminStates.waiting_qr_photo)
    await message.answer(
        f"📷 Отправьте фото QR-кода для <b>{title}</b>:",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_qr_photo)
async def admin_qr_photo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.photo:
        await message.answer("Нужно отправить фото QR-кода.", reply_markup=admin_cancel_kb())
        return
    data = await state.get_data()
    promo_id = data.get("qr_promo_id")
    title = data.get("qr_title")
    await PromotionQRRepository(session).add(promo_id, title, message.photo[-1].file_id)
    qr_codes = await PromotionQRRepository(session).list_for_promo(promo_id)
    await state.clear()
    await message.answer(
        f"✅ QR-код «{title}» добавлен!\n\nВсего QR кодов: {len(qr_codes)}",
        reply_markup=admin_qr_list_kb(promo_id, qr_codes),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_qr_delete:"))
async def admin_qr_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    parts = callback.data.split(":")
    qr_id = int(parts[1])
    promo_id = int(parts[2])
    await PromotionQRRepository(session).delete(qr_id)
    qr_codes = await PromotionQRRepository(session).list_for_promo(promo_id)
    promo = await PromotionRepository(session).get(promo_id)
    deactivated = False
    if not qr_codes and promo and promo.is_active:
        await PromotionRepository(session).deactivate(promo_id)
        deactivated = True
    await callback.message.edit_text(
        f"🗑 Способ оплаты удалён.\n\nОсталось способов: {len(qr_codes)}"
        + ("\n\n⚠️ Акция автоматически снята с публикации." if deactivated else ""),
        reply_markup=admin_qr_list_kb(promo_id, qr_codes),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_qr_template_list:"))
async def admin_qr_template_list(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":", 1)[1])
    qr_codes = await SavedQRRepository(session).list_all()
    text = (
        f"📂 <b>Библиотека QR для акции #{promo_id}</b>\n\n"
        "Нажмите на каждый QR, который нужно включить в эту акцию. "
        "Можно последовательно добавить один, два или несколько QR."
        if qr_codes
        else "📂 <b>Библиотека QR</b>\n\nСохранённых QR пока нет. Добавьте их через кнопку «Библиотека QR-кодов» в админ-панели."
    )
    await callback.message.edit_text(
        text,
        reply_markup=admin_saved_qr_apply_list_kb(promo_id, qr_codes),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_qr_template_apply:"))
async def admin_qr_template_apply(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, promo_id_raw, qr_id_raw = callback.data.split(":")
    promo_id = int(promo_id_raw)
    qr_id = int(qr_id_raw)
    saved_qr = await SavedQRRepository(session).get(qr_id)
    if not saved_qr:
        await callback.answer("Готовый QR не найден.", show_alert=True)
        return
    await PromotionQRRepository(session).add(promo_id, saved_qr.title, saved_qr.file_id)
    qr_codes = await PromotionQRRepository(session).list_for_promo(promo_id)
    await callback.message.edit_text(
        f"✅ QR-код «{escape(saved_qr.title)}» применён к акции.\n\nВсего QR кодов: {len(qr_codes)}",
        reply_markup=admin_qr_list_kb(promo_id, qr_codes),
        parse_mode="HTML",
    )
    await callback.answer()

# ── Шаблоны вариантов покупки ─────────────────────────────────────────────────

@router.callback_query(F.data == "admin_btn_configs")
async def admin_btn_configs(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    configs = await SavedStickerButtonConfigRepository(session).list_all()
    text = (
        "🧩 <b>Шаблоны вариантов покупки</b>\n\nВыберите шаблон для просмотра и изменения."
        if configs else
        "🧩 <b>Шаблоны вариантов покупки</b>\n\nШаблонов пока нет. Создайте первый."
    )
    await callback.message.edit_text(text, reply_markup=admin_button_configs_kb(configs), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_btn_config_add")
async def admin_btn_config_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await state.set_state(AdminStates.waiting_btn_config_title)
    await callback.message.edit_text("Введите название шаблона вариантов покупки:", reply_markup=admin_cancel_kb())
    await callback.answer()


@router.message(AdminStates.waiting_btn_config_title)
async def admin_btn_config_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer("Название слишком короткое.")
        return
    config = await SavedStickerButtonConfigRepository(session).create(title)
    await state.clear()
    await _show_button_config(message, session, config.id, "✅ Шаблон создан.\n\n")


@router.callback_query(F.data.startswith("admin_btn_config:"))
async def admin_btn_config_show(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    config_id = int(callback.data.split(":", 1)[1])
    config = await SavedStickerButtonConfigRepository(session).get(config_id)
    if not config:
        await callback.answer("Шаблон не найден.", show_alert=True)
        return
    await callback.message.edit_text(
        _button_config_text(config),
        reply_markup=admin_button_config_detail_kb(config.id, config.buttons),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_btn_config_edit_title:"))
async def admin_btn_config_edit_title_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    config_id = int(callback.data.split(":", 1)[1])
    await state.update_data(btn_config_id=config_id)
    await state.set_state(AdminStates.waiting_edit_btn_config_title)
    await callback.message.answer("Введите новое название шаблона:", reply_markup=admin_cancel_kb())
    await callback.answer()


@router.message(AdminStates.waiting_edit_btn_config_title)
async def admin_btn_config_edit_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer("Название слишком короткое.")
        return
    data = await state.get_data()
    config = await SavedStickerButtonConfigRepository(session).update_title(int(data["btn_config_id"]), title)
    await state.clear()
    if config:
        await _show_button_config(message, session, config.id, "✅ Название шаблона обновлено.\n\n")
    else:
        await message.answer("Шаблон не найден.", reply_markup=await _admin_panel_kb(session))


@router.callback_query(F.data.startswith("admin_btn_config_btn_add:"))
async def admin_btn_config_btn_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    config_id = int(callback.data.split(":", 1)[1])
    await state.update_data(btn_config_id=config_id)
    await state.set_state(AdminStates.waiting_btn_config_button_label)
    await callback.message.answer(
        "Введите текст кнопки.\n\nНапример: <b>1 Стикер</b> или <b>5 Стикеров + 1 В🎁</b>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_btn_config_button_label)
async def admin_btn_config_button_label(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    label = (message.text or "").strip()
    if not label:
        await message.answer("Текст кнопки не может быть пустым.")
        return
    await state.update_data(btn_config_button_label=label)
    await state.set_state(AdminStates.waiting_btn_config_button_count)
    await message.answer(
        "Введите количество стикеров для этой кнопки.\n\nНапример: <b>1</b>, <b>5</b>, <b>10</b>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_btn_config_button_count)
async def admin_btn_config_button_count(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        count = int((message.text or "").strip())
        if count <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите целое положительное число. Например: 5")
        return
    data = await state.get_data()
    config_id = int(data["btn_config_id"])
    await SavedStickerButtonConfigRepository(session).add_button(config_id, data["btn_config_button_label"], count)
    await state.clear()
    await _show_button_config(message, session, config_id, "✅ Кнопка добавлена в шаблон.\n\n")


@router.callback_query(F.data.startswith("admin_btn_config_btn:"))
async def admin_btn_config_btn_show(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, button_id_raw, config_id_raw = callback.data.split(":")
    button_id = int(button_id_raw)
    config_id = int(config_id_raw)
    button = await SavedStickerButtonConfigRepository(session).get_button(button_id)
    if not button:
        await callback.answer("Кнопка не найдена.", show_alert=True)
        return
    await callback.message.edit_text(
        (
            f"✏️ <b>Кнопка шаблона:</b> {escape(button.label)}\n"
            f"🔢 <b>Стикеров:</b> {button.sticker_count}\n"
            f"↔️ <b>Размер:</b> {_sticker_button_width_text(getattr(button, 'row_width', 1))}"
        ),
        reply_markup=admin_button_config_button_edit_kb(button.id, config_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_btn_config_btn_edit_label:"))
async def admin_btn_config_btn_edit_label_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, button_id_raw, config_id_raw = callback.data.split(":")
    await state.update_data(btn_config_button_id=int(button_id_raw), btn_config_id=int(config_id_raw))
    await state.set_state(AdminStates.waiting_edit_btn_config_button_label)
    await callback.message.answer("Введите новый текст кнопки:", reply_markup=admin_cancel_kb())
    await callback.answer()


@router.message(AdminStates.waiting_edit_btn_config_button_label)
async def admin_btn_config_btn_edit_label(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    label = (message.text or "").strip()
    if not label:
        await message.answer("Текст кнопки не может быть пустым.")
        return
    data = await state.get_data()
    repo = SavedStickerButtonConfigRepository(session)
    button = await repo.get_button(int(data["btn_config_button_id"]))
    if button:
        await repo.update_button(button.id, label, button.sticker_count)
    await state.clear()
    await _show_button_config(message, session, int(data["btn_config_id"]), "✅ Текст кнопки обновлён.\n\n")


@router.callback_query(F.data.startswith("admin_btn_config_btn_edit_count:"))
async def admin_btn_config_btn_edit_count_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, button_id_raw, config_id_raw = callback.data.split(":")
    await state.update_data(btn_config_button_id=int(button_id_raw), btn_config_id=int(config_id_raw))
    await state.set_state(AdminStates.waiting_edit_btn_config_button_count)
    await callback.message.answer("Введите новое количество стикеров:", reply_markup=admin_cancel_kb())
    await callback.answer()


@router.message(AdminStates.waiting_edit_btn_config_button_count)
async def admin_btn_config_btn_edit_count(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        count = int((message.text or "").strip())
        if count <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите целое положительное число.")
        return
    data = await state.get_data()
    repo = SavedStickerButtonConfigRepository(session)
    button = await repo.get_button(int(data["btn_config_button_id"]))
    if button:
        await repo.update_button(button.id, button.label, count)
    await state.clear()
    await _show_button_config(message, session, int(data["btn_config_id"]), "✅ Количество обновлено.\n\n")


@router.callback_query(F.data.startswith("admin_btn_config_btn_move:"))
async def admin_btn_config_btn_move(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, button_id_raw, config_id_raw, direction_raw = callback.data.split(":")
    button_id = int(button_id_raw)
    config_id = int(config_id_raw)
    await SavedStickerButtonConfigRepository(session).move_button(button_id, int(direction_raw))
    config = await SavedStickerButtonConfigRepository(session).get(config_id)
    if not config:
        await callback.answer("Шаблон не найден.", show_alert=True)
        return
    await callback.message.edit_text(
        _button_config_text(config),
        reply_markup=admin_button_config_detail_kb(config.id, config.buttons),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_btn_config_btn_toggle_width:"))
async def admin_btn_config_btn_toggle_width(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, button_id_raw, config_id_raw = callback.data.split(":")
    button_id = int(button_id_raw)
    config_id = int(config_id_raw)
    button = await SavedStickerButtonConfigRepository(session).toggle_button_width(button_id)
    if not button:
        await callback.answer("Кнопка не найдена.", show_alert=True)
        return
    await callback.message.edit_text(
        (
            f"✏️ <b>Кнопка шаблона:</b> {escape(button.label)}\n"
            f"🔢 <b>Стикеров:</b> {button.sticker_count}\n"
            f"↔️ <b>Размер:</b> {_sticker_button_width_text(getattr(button, 'row_width', 1))}"
        ),
        reply_markup=admin_button_config_button_edit_kb(button.id, config_id),
        parse_mode="HTML",
    )
    await callback.answer("Размер переключён.")


@router.callback_query(F.data.startswith("admin_btn_config_btn_delete:"))
async def admin_btn_config_btn_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, button_id_raw, config_id_raw = callback.data.split(":")
    config_id = int(config_id_raw)
    await SavedStickerButtonConfigRepository(session).delete_button(int(button_id_raw))
    config = await SavedStickerButtonConfigRepository(session).get(config_id)
    if not config:
        await callback.answer("Шаблон не найден.", show_alert=True)
        return
    await callback.message.edit_text(
        "🗑 Кнопка удалена.\n\n" + _button_config_text(config),
        reply_markup=admin_button_config_detail_kb(config.id, config.buttons),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_btn_config_delete:"))
async def admin_btn_config_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    config_id = int(callback.data.split(":", 1)[1])
    await SavedStickerButtonConfigRepository(session).delete(config_id)
    configs = await SavedStickerButtonConfigRepository(session).list_all()
    await callback.message.edit_text(
        "🗑 Шаблон удалён.\n\nВыберите следующий шаблон.",
        reply_markup=admin_button_configs_kb(configs),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_btn_config_apply_list:"))
async def admin_btn_config_apply_list(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":", 1)[1])
    configs = await SavedStickerButtonConfigRepository(session).list_all()
    text = (
        "📂 <b>Шаблоны вариантов покупки</b>\n\nВыберите шаблон для этой акции."
        if configs else
        "📂 <b>Шаблоны вариантов покупки</b>\n\nШаблонов пока нет. Создайте их в разделе «Шаблоны вариантов покупки»."
    )
    await callback.message.edit_text(
        text,
        reply_markup=admin_button_config_apply_list_kb(promo_id, configs),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_btn_config_apply:"))
async def admin_btn_config_apply(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, promo_id_raw, config_id_raw = callback.data.split(":")
    promo_id = int(promo_id_raw)
    config_id = int(config_id_raw)
    config = await SavedStickerButtonConfigRepository(session).get(config_id)
    if not config:
        await callback.answer("Шаблон не найден.", show_alert=True)
        return
    if not config.buttons:
        await callback.answer("В этом шаблоне пока нет кнопок.", show_alert=True)
        return
    buttons = await StickerButtonRepository(session).replace_for_promo(promo_id, config.buttons)
    await callback.message.edit_text(
        f"✅ Шаблон «{escape(config.title)}» применён к акции.\n\nКнопок: {len(buttons)}",
        reply_markup=admin_sticker_buttons_kb(promo_id, buttons),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Кнопки стикеров ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin_btn_list:"))
async def admin_btn_list(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":", 1)[1])
    buttons = await StickerButtonRepository(session).list_for_promo(promo_id)
    text = (
        f"🛒 <b>Варианты покупки акции #{promo_id}</b>\n\n"
        "Эти кнопки пользователь увидит <b>до выбора банка</b>. "
        "Надпись и оплачиваемое количество настраиваются отдельно: "
        "например, текст «5 + 1 в подарок», количество для расчёта — 5.\n\n"
    )
    text += (
        f"Вариантов: {len(buttons)}. Нажмите на любой, чтобы изменить."
        if buttons
        else "Вариантов пока нет. Добавьте вручную или загрузите стандартные."
    )
    await callback.message.edit_text(
        text,
        reply_markup=admin_sticker_buttons_kb(promo_id, buttons),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_qr_delete_all_confirm:"))
async def admin_qr_delete_all_confirm(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.rsplit(":", 1)[1])
    await callback.message.edit_text(
        "Удалить <b>все способы оплаты только из этой акции</b>?\n\n"
        "Сохранённые QR-коды в общей библиотеке останутся.",
        reply_markup=admin_qr_delete_all_confirm_kb(promo_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_qr_delete_all:"))
async def admin_qr_delete_all(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.rsplit(":", 1)[1])
    deleted = await PromotionQRRepository(session).delete_all_for_promo(promo_id)
    promo = await PromotionRepository(session).get(promo_id)
    deactivated = False
    if promo and promo.is_active:
        await PromotionRepository(session).deactivate(promo_id)
        deactivated = True
    await callback.message.edit_text(
        f"🗑 Из акции удалено способов оплаты: {deleted}.\n\n"
        "QR-коды в общей библиотеке не удалялись."
        + ("\n\n⚠️ Акция автоматически снята с публикации." if deactivated else ""),
        reply_markup=admin_qr_list_kb(promo_id, []),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_btn_defaults:"))
async def admin_btn_defaults(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.rsplit(":", 1)[1])
    repo = StickerButtonRepository(session)
    buttons = await repo.list_for_promo(promo_id)
    if buttons:
        await callback.answer(
            "В акции уже есть варианты покупки. Измените их по одному или удалите перед загрузкой стандартных.",
            show_alert=True,
        )
        return
    for label, count, row_width in DEFAULT_PURCHASE_BUTTONS:
        await repo.add(promo_id, label, count, row_width)
    buttons = await repo.list_for_promo(promo_id)
    await callback.message.edit_text(
        "✅ Стандартные варианты добавлены. Нажмите на любой вариант, чтобы изменить текст или количество.",
        reply_markup=admin_sticker_buttons_kb(promo_id, buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_btn_add:"))
async def admin_btn_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":", 1)[1])
    await state.update_data(btn_promo_id=promo_id)
    await state.set_state(AdminStates.waiting_btn_label)
    await callback.message.answer(
        "Введите текст кнопки.\n\nНапример: <b>1 Стикер</b> или <b>5 Стикеров + 1 В🎁</b>",
        reply_markup=admin_promo_back_kb(promo_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_btn_label)
async def admin_btn_label(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    label = (message.text or "").strip()
    if len(label) < 1:
        await message.answer("Текст кнопки не может быть пустым.")
        return
    await state.update_data(btn_label=label)
    await state.set_state(AdminStates.waiting_btn_count)
    await message.answer(
        "Введите количество стикеров для этой кнопки.\n\nНапример: <b>1</b>, <b>5</b>, <b>10</b>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_btn_count)
async def admin_btn_count(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        count = int((message.text or "").strip())
        if count <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите целое положительное число. Например: 5")
        return
    data = await state.get_data()
    promo_id = data["btn_promo_id"]
    label = data["btn_label"]
    await StickerButtonRepository(session).add(promo_id, label, count)
    buttons = await StickerButtonRepository(session).list_for_promo(promo_id)
    await state.clear()
    await message.answer(
        f"✅ Кнопка добавлена!\n\nВсего кнопок: {len(buttons)}",
        reply_markup=admin_sticker_buttons_kb(promo_id, buttons),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_btn_edit:"))
async def admin_btn_edit(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    parts = callback.data.split(":")
    btn_id, promo_id = int(parts[1]), int(parts[2])
    btn = await StickerButtonRepository(session).get(btn_id)
    if not btn:
        await callback.answer("Кнопка не найдена", show_alert=True)
        return
    await callback.message.edit_text(
        (
            f"✏️ <b>Кнопка:</b> {escape(btn.label)}\n"
            f"🔢 <b>Стикеров:</b> {btn.sticker_count}\n"
            f"↔️ <b>Размер:</b> {_sticker_button_width_text(getattr(btn, 'row_width', 1))}"
        ),
        reply_markup=admin_btn_edit_kb(btn_id, promo_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_btn_edit_label:"))
async def admin_btn_edit_label_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    parts = callback.data.split(":")
    btn_id, promo_id = int(parts[1]), int(parts[2])
    await state.update_data(edit_btn_id=btn_id, btn_promo_id=promo_id)
    await state.set_state(AdminStates.waiting_edit_btn_label)
    await callback.message.answer("Введите новый текст кнопки:", reply_markup=admin_promo_back_kb(promo_id))
    await callback.answer()


@router.message(AdminStates.waiting_edit_btn_label)
async def admin_btn_edit_label(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    btn = await StickerButtonRepository(session).get(int(data["edit_btn_id"]))
    if btn:
        await StickerButtonRepository(session).update(btn.id, (message.text or "").strip(), btn.sticker_count)
    buttons = await StickerButtonRepository(session).list_for_promo(int(data["btn_promo_id"]))
    await state.clear()
    await message.answer(
        "✅ Текст кнопки обновлён.",
        reply_markup=admin_sticker_buttons_kb(int(data["btn_promo_id"]), buttons),
    )


@router.callback_query(F.data.startswith("admin_btn_edit_count:"))
async def admin_btn_edit_count_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    parts = callback.data.split(":")
    btn_id, promo_id = int(parts[1]), int(parts[2])
    await state.update_data(edit_btn_id=btn_id, btn_promo_id=promo_id)
    await state.set_state(AdminStates.waiting_edit_btn_count)
    await callback.message.answer("Введите новое количество стикеров:", reply_markup=admin_promo_back_kb(promo_id))
    await callback.answer()


@router.message(AdminStates.waiting_edit_btn_count)
async def admin_btn_edit_count(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        count = int((message.text or "").strip())
        if count <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите целое положительное число.")
        return
    data = await state.get_data()
    btn = await StickerButtonRepository(session).get(int(data["edit_btn_id"]))
    if btn:
        await StickerButtonRepository(session).update(btn.id, btn.label, count)
    buttons = await StickerButtonRepository(session).list_for_promo(int(data["btn_promo_id"]))
    await state.clear()
    await message.answer(
        "✅ Количество обновлено.",
        reply_markup=admin_sticker_buttons_kb(int(data["btn_promo_id"]), buttons),
    )


@router.callback_query(F.data.startswith("admin_btn_move:"))
async def admin_btn_move(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, btn_id_raw, promo_id_raw, direction_raw = callback.data.split(":")
    btn_id = int(btn_id_raw)
    promo_id = int(promo_id_raw)
    await StickerButtonRepository(session).move(btn_id, int(direction_raw))
    buttons = await StickerButtonRepository(session).list_for_promo(promo_id)
    await callback.message.edit_text(
        f"🔘 <b>Кнопки стикеров акции #{promo_id}</b>\n\nКнопок: {len(buttons)}",
        reply_markup=admin_sticker_buttons_kb(promo_id, buttons),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_btn_toggle_width:"))
async def admin_btn_toggle_width(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    _, btn_id_raw, promo_id_raw = callback.data.split(":")
    btn_id = int(btn_id_raw)
    promo_id = int(promo_id_raw)
    btn = await StickerButtonRepository(session).toggle_width(btn_id)
    if not btn:
        await callback.answer("Кнопка не найдена.", show_alert=True)
        return
    await callback.message.edit_text(
        (
            f"✏️ <b>Кнопка:</b> {escape(btn.label)}\n"
            f"🔢 <b>Стикеров:</b> {btn.sticker_count}\n"
            f"↔️ <b>Размер:</b> {_sticker_button_width_text(getattr(btn, 'row_width', 1))}"
        ),
        reply_markup=admin_btn_edit_kb(btn_id, promo_id),
        parse_mode="HTML",
    )
    await callback.answer("Размер переключён.")


@router.callback_query(F.data.startswith("admin_btn_delete:"))
async def admin_btn_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    parts = callback.data.split(":")
    btn_id, promo_id = int(parts[1]), int(parts[2])
    await StickerButtonRepository(session).delete(btn_id)
    buttons = await StickerButtonRepository(session).list_for_promo(promo_id)
    await callback.message.edit_text(
        f"🗑 Кнопка удалена.\n\nОсталось кнопок: {len(buttons)}",
        reply_markup=admin_sticker_buttons_kb(promo_id, buttons),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Активация / деактивация ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin_promo_activate:"))
async def admin_promo_activate(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":", 1)[1])
    qr_count = await PromotionQRRepository(session).count_for_promo(promo_id)
    button_count = len(await StickerButtonRepository(session).list_for_promo(promo_id))
    missing = []
    if not button_count:
        missing.append("варианты покупки")
    if not qr_count:
        missing.append("способы оплаты")
    if missing:
        await callback.answer(
            "Нельзя опубликовать: добавьте " + " и ".join(missing) + ".",
            show_alert=True,
        )
        return
    promo = await PromotionRepository(session).activate(promo_id)
    if not promo:
        await callback.answer("Акция не найдена", show_alert=True)
        return
    await callback.message.edit_text(
        "✅ Акция сделана активной.\n\n" + _promo_text(promo, qr_count, button_count),
        reply_markup=admin_promotion_edit_kb(promo.id, promo.is_active),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_promo_deactivate:"))
async def admin_promo_deactivate(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":", 1)[1])
    promo = await PromotionRepository(session).deactivate(promo_id)
    if not promo:
        await callback.answer("Акция не найдена", show_alert=True)
        return
    qr_count = await PromotionQRRepository(session).count_for_promo(promo_id)
    await callback.message.edit_text(
        "⏸ Акция деактивирована.\n\n" + _promo_text(promo, qr_count),
        reply_markup=admin_promotion_edit_kb(promo.id, promo.is_active),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Редактирование полей акции ────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin_promo_edit_title:"))
async def admin_promo_edit_title_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":", 1)[1])
    promo = await PromotionRepository(session).get(promo_id)
    current = promo.title if promo else "не задано"
    await state.set_state(AdminStates.waiting_edit_promo_title)
    await state.update_data(edit_promo_id=promo_id)
    await callback.message.edit_text(
        f"Текущее название акции:\n\n<i>{current}</i>\n\n"
        "Отправьте новый текст.",
        reply_markup=admin_back_kb(promo_id),
    )
    await callback.answer()


@router.message(AdminStates.waiting_edit_promo_title)
async def admin_promo_edit_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer("Название слишком короткое. Попробуйте еще раз.")
        return
    data = await state.get_data()
    promo = await PromotionRepository(session).update_title(int(data["edit_promo_id"]), title)
    await state.clear()
    await _show_promo(message, session, promo)


@router.callback_query(F.data.startswith("admin_promo_edit_prize:"))
async def admin_promo_edit_prize_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":", 1)[1])
    await state.set_state(AdminStates.waiting_edit_promo_prize)
    await state.update_data(edit_promo_id=promo_id)
    await callback.message.edit_text(
        "Введите новое название акции для пользователей.\n\n"
        "Оно будет видно в главном меню и при выборе акции.",
        reply_markup=admin_promo_back_kb(promo_id),
    )
    await callback.answer()


@router.message(AdminStates.waiting_edit_promo_prize)
async def admin_promo_edit_prize(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    prize = (message.text or "").strip()
    if len(prize) < 2:
        await message.answer("Название слишком короткое. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    promo = await PromotionRepository(session).update_prize(int(data["edit_promo_id"]), prize)
    await state.clear()
    await _show_promo(message, session, promo)

@router.callback_query(F.data.startswith("admin_promo_edit_price:"))
async def admin_promo_edit_price_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":", 1)[1])
    promo = await PromotionRepository(session).get(promo_id)
    await state.set_state(AdminStates.waiting_edit_promo_price)
    await state.update_data(edit_promo_id=promo_id)
    await callback.message.edit_text(
        f"Текущая цена: <b>{promo.price_per_sticker:.2f} ₽</b>\n\nВведите новую цену за 1 стикер:",
        reply_markup=admin_promo_back_kb(promo_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_edit_promo_price)
async def admin_promo_edit_price(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        price = float((message.text or "").strip().replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректную цену. Например: 1999.9")
        return
    data = await state.get_data()
    promo = await PromotionRepository(session).update_price(int(data["edit_promo_id"]), price)
    await state.clear()
    await _show_promo(message, session, promo)


@router.callback_query(F.data.startswith("admin_promo_edit_photo:"))
async def admin_promo_edit_photo_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":", 1)[1])
    await state.set_state(AdminStates.waiting_edit_promo_photo)
    await state.update_data(edit_promo_id=promo_id)
    await callback.message.edit_text("Отправьте новое фото акции:", reply_markup=admin_promo_back_kb(promo_id))
    await callback.answer()

@router.callback_query(F.data.startswith("admin_promo_edit_desc:"))
async def admin_promo_edit_desc_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":", 1)[1])
    promo = await PromotionRepository(session).get(promo_id)
    current = promo.description or "не задано"
    await state.set_state(AdminStates.waiting_edit_promo_desc)
    await state.update_data(edit_promo_id=promo_id)
    await callback.message.edit_text(
        f"Текущее описание:\n\n<i>{current}</i>\n\n"
        "Отправьте новое описание акции: призы, их количество и другие условия.\n"
        "<b>Пользователь увидит этот текст перед кнопкой «Купить стикер».</b>\n"
        "Поддерживаются форматы: <b>жирный</b>, <i>курсив</i>",
        reply_markup=admin_promo_back_kb(promo_id),
        parse_mode="HTML",
    )
    await callback.answer()

@router.callback_query(F.data.startswith("admin_promo_edit_payment_text:"))
async def admin_promo_edit_payment_text_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":", 1)[1])
    promo = await PromotionRepository(session).get(promo_id)
    current = promo.payment_text or "не задан (используется общая инструкция)"
    await state.set_state(AdminStates.waiting_edit_promo_payment_text)
    await state.update_data(edit_promo_id=promo_id)
    await callback.message.edit_text(
        f"Текущая инструкция этой акции:\n\n<i>{current}</i>\n\n"
        "Это необязательное поле. Если его не заполнять, бот использует общую "
        "инструкцию из раздела «Тексты и контакты оплаты».\n\n"
        "Отправьте отдельную инструкцию только если она отличается для этой акции.\n"
        "Поддерживаются форматы: <b>жирный</b>, <i>курсив</i>\n\n"
        "Доступные переменные:\n"
        "<code>{price}</code> — цена за 1 стикер\n"
        "<code>{total}</code> — итоговая сумма выбранного количества стикеров\n"
        "<code>{count}</code> — количество стикеров которое выбрал пользователь\n"
        "<code>{manager}</code> — username менеджера для отправки чека",
        reply_markup=admin_payment_text_kb(),
        parse_mode="HTML",
    )
    await callback.answer()

@router.callback_query(F.data == "admin_promo_payment_text_default")
async def admin_promo_payment_text_default(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    data = await state.get_data()
    promo_id = data.get("edit_promo_id")
    if not promo_id:
        await callback.answer("Акция не найдена", show_alert=True)
        return
    promo = await PromotionRepository(session).update_payment_text(int(promo_id), None)
    await state.clear()
    await callback.answer("✅ Теперь используется общая инструкция")
    await _show_promo(callback.message, session, promo)


@router.message(AdminStates.waiting_edit_promo_payment_text)
async def admin_promo_edit_payment_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    promo = await PromotionRepository(session).update_payment_text(
        int(data["edit_promo_id"]),
        message.html_text or message.text or "",
    )
    await state.clear()
    await _show_promo(message, session, promo)

@router.message(AdminStates.waiting_edit_promo_desc)
async def admin_promo_edit_desc(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    promo = await PromotionRepository(session).update_description(
        int(data["edit_promo_id"]),
        message.html_text or message.text or "",
    )
    await state.clear()
    await _show_promo(message, session, promo)

@router.message(AdminStates.waiting_edit_promo_photo)
async def admin_promo_edit_photo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.photo:
        await message.answer("Пожалуйста, отправьте именно фото.")
        return
    data = await state.get_data()
    promo = await PromotionRepository(session).update_photo(int(data["edit_promo_id"]), message.photo[-1].file_id)
    await state.clear()
    await _show_promo(message, session, promo)


@router.callback_query(F.data.startswith("admin_promo_delete:"))
async def admin_promo_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":", 1)[1])
    deleted = await PromotionRepository(session).delete(promo_id)
    promos = await PromotionRepository(session).list_all()
    text = "🗑 Акция удалена.\n\nВыберите следующую акцию." if deleted else "Акция не найдена."
    await callback.message.edit_text(text, reply_markup=admin_promotions_kb(promos))
    await callback.answer()


# ── Рассылка ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_broadcast)
    await callback.message.edit_text(
        "📢 Отправьте сообщение для рассылки.\n\nМожно отправить текст или фото с подписью.",
        reply_markup=admin_cancel_kb(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_broadcast)
async def admin_broadcast_send(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    users = await UserRepository(session).list_broadcast_targets()
    sent = 0
    failed = 0
    for user in users:
        try:
            if message.photo:
                await bot.send_photo(user.telegram_id, message.photo[-1].file_id, caption=message.caption)
            else:
                await bot.send_message(user.telegram_id, message.html_text or message.text or "", parse_mode="HTML")
            sent += 1
        except Exception as e:
            failed += 1
            logger.warning("Broadcast failed for user %s: %s", user.telegram_id, e)
    await state.clear()
    await message.answer(
        f"📢 Рассылка завершена.\n\n✅ Отправлено: {sent}\n❌ Ошибок: {failed}",
        reply_markup=await _admin_panel_kb(session),
    )
#── Приветствие ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_edit_welcome")
async def admin_edit_welcome_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    from bot.repositories import SettingsRepository
    current = await SettingsRepository(session).get("welcome_text", "не задано")
    await state.set_state(AdminStates.waiting_welcome_text)
    await callback.message.edit_text(
        f"Текущее приветствие:\n\n<i>{current}</i>\n\n"
        "Отправьте новый текст.\n"
        "Поддерживаются форматы: <b>жирный</b>, <i>курсив</i>\n\n"
        "Доступные переменные:\n"
        "<code>{prizes}</code> — названия всех активных акций для пользователей\n"
        "<code>{prize}</code> — название первой акции для пользователей",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_welcome_text)
async def admin_edit_welcome_save(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    from bot.repositories import SettingsRepository
    text = message.html_text or message.text or ""
    if len(text) < 5:
        await message.answer("Текст слишком короткий.")
        return
    await SettingsRepository(session).set("welcome_text", text)
    await state.clear()
    await message.answer("✅ Приветствие обновлено!", reply_markup=await _admin_panel_kb(session))


@router.callback_query(F.data == "admin_edit_join_button")
async def admin_edit_join_button_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not is_admin(callback.from_user.id):
        return
    current = await SettingsRepository(session).get(MAIN_JOIN_BUTTON_LABEL_KEY, "УЧАСТВОВАТЬ")
    await state.set_state(AdminStates.waiting_main_join_button_label)
    await callback.message.edit_text(
        f"Текущее название кнопки: <b>{escape(current)}</b>\n\n"
        "Введите новое название кнопки участия в главном меню.",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_main_join_button_label)
async def admin_edit_join_button_save(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if not is_admin(message.from_user.id):
        return
    label = " ".join((message.text or "").split())
    if len(label) < 2 or len(label) > 64:
        await message.answer("Название должно содержать от 2 до 64 символов.")
        return
    await SettingsRepository(session).set(MAIN_JOIN_BUTTON_LABEL_KEY, label)
    await state.clear()
    await message.answer("✅ Название кнопки участия обновлено.", reply_markup=await _admin_panel_kb(session))


@router.callback_query(F.data == "admin_edit_warning_text")
async def admin_edit_warning_text_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not is_admin(callback.from_user.id):
        return
    current = await SettingsRepository(session).get(
        WARNING_TEXT_KEY,
        "Используется исходное предупреждение из бота.",
    )
    shown = current or "выключено"
    await state.set_state(AdminStates.waiting_warning_text)
    await callback.message.edit_text(
        f"Текущее предупреждение:\n\n<i>{shown}</i>\n\n"
        "Отправьте новый текст. Чтобы полностью убрать предупреждение, "
        "отправьте слово <code>ВЫКЛЮЧИТЬ</code>.",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_warning_text)
async def admin_edit_warning_text_save(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if not is_admin(message.from_user.id):
        return
    text = message.html_text or message.text or ""
    value = "" if (message.text or "").strip().casefold() == "выключить" else text
    if value and len(value.strip()) < 5:
        await message.answer("Текст слишком короткий или отправьте слово ВЫКЛЮЧИТЬ.")
        return
    await SettingsRepository(session).set(WARNING_TEXT_KEY, value)
    await state.clear()
    result = "выключено" if not value else "обновлено"
    await message.answer(f"✅ Предупреждение {result}.", reply_markup=await _admin_panel_kb(session))


async def _post_payment_values(session: AsyncSession) -> dict[str, tuple[bool, str]]:
    repo = SettingsRepository(session)
    result = {}
    for key, default_label in POST_PAYMENT_DEFAULTS.items():
        enabled = await repo.get(f"post_{key}_enabled", "1") != "0"
        label = await repo.get(f"post_{key}_label", default_label)
        result[key] = (enabled, label)
    return result


@router.callback_query(F.data == "admin_post_payment_settings")
async def admin_post_payment_settings(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text(
        "🔘 <b>Кнопки после оплаты</b>\n\n"
        "Каждую кнопку можно переименовать или выключить. "
        "Приём чеков и ручная выдача номеров внутри бота пока выключены: "
        "по умолчанию чек отправляется внешнему менеджеру.",
        reply_markup=admin_post_payment_settings_kb(await _post_payment_values(session)),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_post_payment_item:"))
async def admin_post_payment_item(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    key = callback.data.rsplit(":", 1)[1]
    if key not in POST_PAYMENT_DEFAULTS:
        await callback.answer("Настройка не найдена.", show_alert=True)
        return
    repo = SettingsRepository(session)
    enabled = await repo.get(f"post_{key}_enabled", "1") != "0"
    label = await repo.get(f"post_{key}_label", POST_PAYMENT_DEFAULTS[key])
    await callback.message.edit_text(
        f"Кнопка: <b>{escape(label)}</b>\n"
        f"Состояние: <b>{'включена' if enabled else 'выключена'}</b>",
        reply_markup=admin_post_payment_item_kb(
            key,
            enabled,
            has_text=key in {"how_to_pay", "where_number"},
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_post_payment_toggle:"))
async def admin_post_payment_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    key = callback.data.rsplit(":", 1)[1]
    if key not in POST_PAYMENT_DEFAULTS:
        return
    repo = SettingsRepository(session)
    enabled = await repo.get(f"post_{key}_enabled", "1") != "0"
    await repo.set(f"post_{key}_enabled", "0" if enabled else "1")
    await callback.answer("Настройка сохранена.")
    values = await _post_payment_values(session)
    await callback.message.edit_text(
        "🔘 <b>Кнопки после оплаты</b>",
        reply_markup=admin_post_payment_settings_kb(values),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_post_payment_label:"))
async def admin_post_payment_label_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    key = callback.data.rsplit(":", 1)[1]
    if key not in POST_PAYMENT_DEFAULTS:
        return
    await state.update_data(post_payment_key=key)
    await state.set_state(AdminStates.waiting_post_payment_label)
    await callback.message.edit_text(
        "Введите новое название кнопки.",
        reply_markup=admin_cancel_kb(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_post_payment_label)
async def admin_post_payment_label_save(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if not is_admin(message.from_user.id):
        return
    label = " ".join((message.text or "").split())
    if len(label) < 2 or len(label) > 64:
        await message.answer("Название должно содержать от 2 до 64 символов.")
        return
    data = await state.get_data()
    key = data.get("post_payment_key")
    if key not in POST_PAYMENT_DEFAULTS:
        await state.clear()
        return
    await SettingsRepository(session).set(f"post_{key}_label", label)
    await state.clear()
    await message.answer(
        "✅ Название кнопки сохранено.",
        reply_markup=admin_post_payment_settings_kb(await _post_payment_values(session)),
    )


@router.callback_query(F.data.startswith("admin_post_payment_text:"))
async def admin_post_payment_text_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    key = callback.data.rsplit(":", 1)[1]
    if key not in {"how_to_pay", "where_number"}:
        return
    await state.update_data(post_payment_key=key)
    await state.set_state(AdminStates.waiting_post_payment_text)
    await callback.message.edit_text(
        "Отправьте сообщение, которое пользователь увидит после нажатия этой кнопки.",
        reply_markup=admin_cancel_kb(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_post_payment_text)
async def admin_post_payment_text_save(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if not is_admin(message.from_user.id):
        return
    text = message.html_text or message.text or ""
    if len(text.strip()) < 5:
        await message.answer("Сообщение слишком короткое.")
        return
    data = await state.get_data()
    key = data.get("post_payment_key")
    if key not in {"how_to_pay", "where_number"}:
        await state.clear()
        return
    await SettingsRepository(session).set(f"post_{key}_text", text)
    await state.clear()
    await message.answer(
        "✅ Сообщение сохранено.",
        reply_markup=admin_post_payment_settings_kb(await _post_payment_values(session)),
    )


@router.callback_query(F.data == "admin_edit_payment_instruction")
async def admin_edit_payment_instruction_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not is_admin(callback.from_user.id):
        return
    saved = await SettingsRepository(session).get(PAYMENT_INSTRUCTION_TEXT_KEY, "")
    manager = await SettingsRepository(session).get(
        PAYMENT_MANAGER_USERNAME_KEY,
        settings.payment_manager_username,
    )
    current = saved or build_default_payment_instruction(
        price="{price}",
        manager=manager,
        support=settings.support_username,
    )
    source = "Ваш текст" if saved else "Стандартный текст — сейчас используется"
    await state.set_state(AdminStates.waiting_payment_instruction_text)
    await callback.message.edit_text(
        f"📝 <b>{source}</b>\n\n{current}\n\n"
        "Если внутри конкретной акции заполнена своя инструкция, она заменяет этот общий текст только для той акции.\n\n"
        "Предупреждение из раздела «Главное меню» добавляется к сообщению автоматически.\n\n"
        "Отправьте сюда новый текст инструкции оплаты"
        " или нажмите кнопку ниже, чтобы вернуть дефолтный текст.\n\n"
        "Поддерживаются форматы: <b>жирный</b>, <i>курсив</i>\n\n"
        "Переменные: <code>{price}</code> — цена за единицу, "
        "<code>{total}</code> — итоговая сумма, <code>{count}</code> — количество, "
        "<code>{manager}</code> — менеджер.",
        reply_markup=admin_payment_instruction_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_payment_instruction_text)
async def admin_edit_payment_instruction_save(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    text = message.html_text or message.text or ""
    if len(text.strip()) < 5:
        await message.answer("Текст слишком короткий.", reply_markup=admin_payment_instruction_kb())
        return
    await SettingsRepository(session).set(PAYMENT_INSTRUCTION_TEXT_KEY, text)
    await state.clear()
    await message.answer(
        "✅ Инструкция оплаты обновлена!",
        reply_markup=admin_payment_settings_kb(await get_qr_auto_delete_hours(session)),
    )


@router.callback_query(F.data == "admin_payment_instruction_default")
async def admin_payment_instruction_default(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    await SettingsRepository(session).set(PAYMENT_INSTRUCTION_TEXT_KEY, "")
    await state.clear()
    await callback.message.edit_text(
        "✅ Дефолтный текст инструкции оплаты установлен.",
        reply_markup=admin_payment_settings_kb(await get_qr_auto_delete_hours(session)),
    )
    await callback.answer()

# ── Статистика ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_edit_bank_choice_text")
async def admin_edit_bank_choice_text_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not is_admin(callback.from_user.id):
        return
    saved = await SettingsRepository(session).get(BANK_CHOICE_TEXT_KEY, "")
    current = saved or DEFAULT_BANK_CHOICE_TEXT
    source = "Ваш текст" if saved else "Стандартный текст — сейчас используется"
    await state.set_state(AdminStates.waiting_bank_choice_text)
    await callback.message.edit_text(
        f"🏦 <b>{source}</b>\n\n{current}\n\n"
        "Этот текст показывается, когда у акции доступно несколько способов оплаты. "
        "Если способ один, выбор банка пропускается.\n\n"
        "Предупреждение из раздела «Главное меню» добавляется к сообщению автоматически.\n\n"
        "Отправьте сюда новый текст сообщения перед выбором банка"
        " или нажмите кнопку ниже, чтобы вернуть дефолтный текст.\n\n"
        "Поддерживаются форматы: <b>жирный</b>, <i>курсив</i>",
        reply_markup=admin_bank_choice_text_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_bank_choice_text)
async def admin_edit_bank_choice_text_save(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    text = message.html_text or message.text or ""
    if len(text.strip()) < 5:
        await message.answer("Текст слишком короткий.", reply_markup=admin_bank_choice_text_kb())
        return
    await SettingsRepository(session).set(BANK_CHOICE_TEXT_KEY, text)
    await state.clear()
    await message.answer(
        "✅ Текст выбора банка обновлен!",
        reply_markup=admin_payment_settings_kb(await get_qr_auto_delete_hours(session)),
    )


@router.callback_query(F.data == "admin_bank_choice_text_default")
async def admin_bank_choice_text_default(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    await SettingsRepository(session).set(BANK_CHOICE_TEXT_KEY, "")
    await state.clear()
    await callback.message.edit_text(
        "✅ Дефолтный текст выбора банка установлен.",
        reply_markup=admin_payment_settings_kb(await get_qr_auto_delete_hours(session)),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_edit_stickers_text")
async def admin_edit_stickers_text_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not is_admin(callback.from_user.id):
        return
    current = await SettingsRepository(session).get(STICKERS_TEXT_KEY, "используется дефолтный текст")
    await state.set_state(AdminStates.waiting_stickers_text)
    await callback.message.edit_text(
        f"Текущий общий текст сообщения над кнопками стикеров:\n\n<i>{current}</i>\n\n"
        "Отправьте сюда новый общий текст, который показывается над кнопками выбора количества"
        " или нажмите кнопку ниже, чтобы вернуть дефолтный текст.\n\n"
        "Поддерживаются форматы: <b>жирный</b>, <i>курсив</i>",
        reply_markup=admin_stickers_text_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_stickers_text)
async def admin_edit_stickers_text_save(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    text = message.html_text or message.text or ""
    if len(text.strip()) < 5:
        await message.answer("Текст слишком короткий.", reply_markup=admin_stickers_text_kb())
        return
    await SettingsRepository(session).set(STICKERS_TEXT_KEY, text)
    await state.clear()
    await message.answer("✅ Общий текст над кнопками стикеров обновлен!", reply_markup=await _admin_panel_kb(session))


@router.callback_query(F.data == "admin_stickers_text_default")
async def admin_stickers_text_default(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    await SettingsRepository(session).set(STICKERS_TEXT_KEY, "")
    await state.clear()
    await callback.message.edit_text(
        "✅ Дефолтный общий текст над кнопками стикеров установлен.",
        reply_markup=await _admin_panel_kb(session),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_edit_payment_manager")
async def admin_edit_payment_manager_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not is_admin(callback.from_user.id):
        return
    saved = await SettingsRepository(session).get(PAYMENT_MANAGER_USERNAME_KEY, "")
    current = saved or settings.payment_manager_username or "не задан"
    await state.set_state(AdminStates.waiting_payment_manager_username)
    await callback.message.edit_text(
        f"Текущий профиль для кнопки «ОТПРАВИТЬ ЧЕК МЕНЕДЖЕРУ»:\n\n"
        f"<b>@{escape(current.lstrip('@'))}</b>\n\n"
        "Отправьте новый username менеджера.\n"
        "Можно прислать <code>@username</code>, <code>username</code> или ссылку <code>https://t.me/username</code>.",
        reply_markup=admin_payment_manager_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_payment_manager_username)
async def admin_edit_payment_manager_save(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    username = _normalize_telegram_username(message.text or "")
    if not username:
        await message.answer(
            "Не получилось распознать username. Отправьте, например: @yurov_support или https://t.me/yurov_support",
            reply_markup=admin_payment_manager_kb(),
        )
        return
    await SettingsRepository(session).set(PAYMENT_MANAGER_USERNAME_KEY, username)
    await state.clear()
    await message.answer(
        f"✅ Профиль для отправки чеков обновлен: <b>@{escape(username)}</b>",
        reply_markup=await _admin_panel_kb(session),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if not is_admin(callback.from_user.id):
        return
    user_repo = UserRepository(session)
    payment_repo = PaymentRepository(session)
    promo_repo = PromotionRepository(session)

    total_users = await user_repo.count_total()
    pending = await payment_repo.count_by_status(PaymentStatus.pending)
    confirmed = await payment_repo.count_by_status(PaymentStatus.confirmed)
    rejected = await payment_repo.count_by_status(PaymentStatus.rejected)
    revenue = await payment_repo.sum_confirmed()
    promos = await promo_repo.list_all()
    active = await promo_repo.get_active()

    svc = AdminService(bot)
    text = await svc.get_stats_text(total_users, pending, confirmed, rejected, revenue)
    text += f"\n\n🎁 Акций: <b>{len(promos)}</b>"
    active_title = active.title if active else "нет"
    text += f"\nАктивная: <b>{escape(active_title)}</b>"
    await callback.message.edit_text(text, reply_markup=await _admin_panel_kb(session), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_export_participants")
async def admin_export_participants(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    participants = await UserRepository(session).list_for_export()
    if not participants:
        await callback.answer("В базе пока нет пользователей.", show_alert=True)
        return

    filename = f"participants_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.csv"
    document = BufferedInputFile(build_participants_csv(participants), filename=filename)
    await callback.message.answer_document(
        document,
        caption=(
            f"📥 Пользователей в выгрузке: <b>{len(participants)}</b>.\n"
            "Файл открывается в Excel. Если ФИО, город или телефон не заполнены, ячейка останется пустой. "
            "Изменения ФИО, телефона и города показаны в отдельных колонках истории."
        ),
        parse_mode="HTML",
    )
    await callback.answer("Выгрузка готова")


# ── Заявки оплат ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_pending")
async def admin_pending(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if not is_admin(callback.from_user.id):
        return
    payments = await PaymentService(PaymentRepository(session)).get_pending()
    if not payments:
        await callback.answer("Непроверенных оплат нет", show_alert=True)
        return
    for payment in payments:
        user = payment.user
        text = (
            f"💰 <b>Оплата #{payment.id}</b>\n"
            f"Пользователь: {escape(user.full_name)} (@{escape(user.username or 'нет')})\n"
            f"TG ID: <code>{user.telegram_id}</code>\n"
            f"Сумма: <b>{payment.amount} ₽</b>\n"
            f"Метод: {escape(payment.payment_method)}"
        )
        if payment.screenshot_file_id:
            await bot.send_photo(
                callback.from_user.id,
                payment.screenshot_file_id,
                caption=text,
                reply_markup=admin_payment_kb(payment.id),
                parse_mode="HTML",
            )
        else:
            await bot.send_message(
                callback.from_user.id,
                text,
                reply_markup=admin_payment_kb(payment.id),
                parse_mode="HTML",
            )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_confirm:"))
async def admin_confirm(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if not is_admin(callback.from_user.id):
        return
    payment_id = int(callback.data.split(":", 1)[1])
    payment_svc = PaymentService(PaymentRepository(session))
    access_svc = AccessService(AccessRepository(session), bot)

    payment = await payment_svc.confirm(payment_id)
    if not payment:
        await callback.answer("Оплата не найдена", show_alert=True)
        return

    invite = await access_svc.grant_access(payment.user_id, payment.user.telegram_id)
    try:
        await bot.send_message(
            payment.user.telegram_id,
            (
                "✅ <b>Оплата подтверждена!</b>\n\n"
                f"Сумма: <b>{payment.amount} ₽</b>\n\n"
                f"Ссылка доступа:\n{invite}"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("Failed to notify user %s: %s", payment.user.telegram_id, e)

    text = (callback.message.caption or callback.message.text or "") + "\n\n✅ <b>ПОДТВЕРЖДЕНО</b>"
    if callback.message.caption:
        await callback.message.edit_caption(caption=text, parse_mode="HTML")
    else:
        await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer("Оплата подтверждена")


@router.callback_query(F.data.startswith("admin_reject:"))
async def admin_reject_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    payment_id = int(callback.data.split(":", 1)[1])
    await state.set_state(AdminStates.waiting_reject_reason)
    await state.update_data(reject_payment_id=payment_id)
    await callback.message.answer("Введите причину отклонения:", reply_markup=admin_cancel_kb())
    await callback.answer()


@router.message(AdminStates.waiting_reject_reason)
async def admin_reject_reason(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    reason = (message.text or "").strip()
    payment = await PaymentService(PaymentRepository(session)).reject(int(data["reject_payment_id"]), reason)
    if payment:
        try:
            await bot.send_message(
                payment.user.telegram_id,
                (
                    "❌ <b>Оплата отклонена</b>\n\n"
                    f"Причина: {escape(reason)}\n\n"
                    f"Если это ошибка, напишите @{settings.support_username}"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("Failed to notify rejected payment user: %s", e)
    await state.clear()
    await message.answer("Оплата отклонена, пользователь уведомлен.", reply_markup=await _admin_panel_kb(session))


# ── Бан ───────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_ban")
async def admin_ban_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_ban_id)
    await callback.message.edit_text(
        "Введите Telegram ID пользователя, которого нужно забанить или разбанить:",
        reply_markup=admin_cancel_kb(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_ban_id)
async def admin_ban_user(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        target_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите числовой Telegram ID.")
        return

    user_svc = UserService(UserRepository(session))
    user = await user_svc.get_profile(target_id)
    if not user:
        await state.clear()
        await message.answer("Пользователь не найден в базе.", reply_markup=await _admin_panel_kb(session))
        return

    from bot.models import UserRole
    if user.role == UserRole.banned:
        await user_svc.unban(target_id)
        result_text = f"✅ Пользователь <code>{target_id}</code> разбанен."
    else:
        await user_svc.ban(target_id)
        result_text = f"🚫 Пользователь <code>{target_id}</code> забанен."

    await state.clear()
    await message.answer(result_text, reply_markup=await _admin_panel_kb(session), parse_mode="HTML")
