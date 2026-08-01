from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb(show_admin: bool = False, join_label: str = "УЧАСТВОВАТЬ") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=join_label, callback_data="giveaway_join")
    if show_admin:
        builder.button(text="🔐 Админ-панель", callback_data="admin_open")
    builder.button(text="↩️ Все разделы", callback_data="menu:gateway")
    builder.adjust(1)
    return builder.as_markup()


def phone_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отправить номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

def admin_promo_back_kb(promotion_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад к акции", callback_data=f"admin_promo:{promotion_id}")
    builder.adjust(1)
    return builder.as_markup()

def remove_reply_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def buy_sticker_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Купить стикер", callback_data="buy_sticker")
    builder.adjust(1)
    return builder.as_markup()


def buy_sticker_with_phone_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Купить стикер", callback_data="buy_sticker")
    builder.button(text="👤 Мои данные", callback_data="my_phone")
    builder.adjust(1)
    return builder.as_markup()


def my_phone_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить номер", callback_data="change_phone")
    builder.button(text="✏️ Изменить ФИО", callback_data="change_full_name")
    builder.button(text="✏️ Изменить город", callback_data="change_city")
    builder.button(text="⬅️ Назад", callback_data="giveaway_join")
    builder.adjust(1)
    return builder.as_markup()


def bank_choice_kb(qr_codes: list) -> InlineKeyboardMarkup:
    """Клавиатура выбора способа оплаты на основе QR кодов акции."""
    builder = InlineKeyboardBuilder()
    for qr in qr_codes:
        builder.button(text=qr.title, callback_data=f"qr_select:{qr.id}")
    builder.adjust(1)
    return builder.as_markup()


def sticker_count_kb() -> InlineKeyboardMarkup:     #сейчас не используется
    builder = InlineKeyboardBuilder()
    builder.button(text="1 Стикер", callback_data="stickers:1")
    builder.button(text="2 Стикера", callback_data="stickers:2")
    builder.button(text="3 Стикера", callback_data="stickers:3")
    builder.button(text="5 Стикеров + 1 В🎁", callback_data="stickers:5")
    builder.button(text="10 Стикеров + 2 В 🎁", callback_data="stickers:10")
    builder.button(text="🔢 Другое количество", callback_data="stickers_custom")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def payment_result_kb(manager_username: str) -> InlineKeyboardMarkup:
    manager_url = f"https://t.me/{manager_username.lstrip('@')}"
    builder = InlineKeyboardBuilder()
    builder.button(text="ОТПРАВИТЬ ЧЕК МЕНЕДЖЕРУ ↗", url=manager_url)
    builder.button(text="Купить еще", callback_data="buy_sticker")
    builder.button(text="Как оплатить ❓", callback_data="how_to_pay")
    builder.button(text="Ау! Где мой номерок?", callback_data="where_number")
    builder.adjust(1, 2, 1)
    return builder.as_markup()


def back_kb(callback_data: str = "buy_sticker") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data=callback_data)
    builder.adjust(1)
    return builder.as_markup()

def admin_back_kb(promo_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Назад",
        callback_data=f"admin_promo:{promo_id}"
    )
    return builder.as_markup()


def admin_payment_kb(payment_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"admin_confirm:{payment_id}")
    builder.button(text="❌ Отклонить", callback_data=f"admin_reject:{payment_id}")
    builder.adjust(2)
    return builder.as_markup()


def admin_panel_kb(main_menu_photo_exists: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Акции", callback_data="admin_promos")
    builder.button(text="QR-коды", callback_data="admin_saved_qrs")
    builder.button(text="Рассылка", callback_data="admin_broadcast")
    builder.button(text="Забанить / разбанить", callback_data="admin_ban")
    builder.button(text="изменить приветствие", callback_data="admin_edit_welcome")
    builder.button(text="изменить инструкцию оплаты", callback_data="admin_edit_payment_instruction")
    builder.button(text="изменить текст выбора банка", callback_data="admin_edit_bank_choice_text")
    builder.button(text="изменить общий текст над кнопками", callback_data="admin_edit_stickers_text")
    builder.button(text="изменить менеджера для чеков", callback_data="admin_edit_payment_manager")
    builder.button(text="Шаблоны вариантов покупки", callback_data="admin_btn_configs")
    if main_menu_photo_exists:
        builder.button(text="Удалить фото главного меню", callback_data="admin_main_menu_photo_delete")
    else:
        builder.button(text="Добавить фото главного меню", callback_data="admin_main_menu_photo_add")
    builder.button(text="❓ Справка", callback_data="admin_help")
    builder.adjust(2, 2, 1, 1, 1, 1, 1, 1, 1)
    return builder.as_markup()

def admin_help_choice_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔐 Главная панель", callback_data="admin_help_main")
    builder.button(text="🎁 Настройки акции", callback_data="admin_help_promo")
    builder.button(text="⬅️ Назад", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()


def admin_promotions_kb(promotions) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for promo in promotions:
        mark = "✅ " if promo.is_active else ""
        builder.button(text=f"{mark}#{promo.id} {promo.title}", callback_data=f"admin_promo:{promo.id}")
    builder.button(text="Добавить акцию", callback_data="admin_promo_add")
    builder.button(text="Назад", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()


def admin_promotion_edit_kb(promotion_id: int, is_active: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not is_active:
        builder.button(text="✅ Сделать активной", callback_data=f"admin_promo_activate:{promotion_id}")
    else:
        builder.button(text="⏸ Деактивировать", callback_data=f"admin_promo_deactivate:{promotion_id}")
    builder.button(text="📷 Управление QR кодами", callback_data=f"admin_promo_qr_list:{promotion_id}")
    builder.button(text="Изменить название", callback_data=f"admin_promo_edit_title:{promotion_id}")
    builder.button(text="Название для пользователей", callback_data=f"admin_promo_edit_prize:{promotion_id}")
    builder.button(text="Изменить фото", callback_data=f"admin_promo_edit_photo:{promotion_id}")
    builder.button(text="Изменить цену за стикер", callback_data=f"admin_promo_edit_price:{promotion_id}")
    builder.button(text="Изменить описание", callback_data=f"admin_promo_edit_desc:{promotion_id}")
    builder.button(text="Изменить текст оплаты", callback_data=f"admin_promo_edit_payment_text:{promotion_id}")
    builder.button(text="🔘 Кнопки стикеров", callback_data=f"admin_btn_list:{promotion_id}")
    builder.button(text="К списку акций", callback_data="admin_promos")
    builder.button(text="Удалить", callback_data=f"admin_promo_delete:{promotion_id}")
    builder.adjust(1)
    return builder.as_markup()


def admin_qr_list_kb(promotion_id: int, qr_codes: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for qr in qr_codes:
        builder.button(text=f"🗑 {qr.title}", callback_data=f"admin_qr_delete:{qr.id}:{promotion_id}")
    builder.button(text="➕ Добавить QR", callback_data=f"admin_qr_add:{promotion_id}")
    builder.button(text="📂 Применить готовый QR", callback_data=f"admin_qr_template_list:{promotion_id}")
    builder.button(text="⬅️ Назад", callback_data=f"admin_promo:{promotion_id}")
    builder.adjust(1)
    return builder.as_markup()


def admin_saved_qr_list_kb(qr_codes: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for qr in qr_codes:
        builder.button(text=f"#{qr.id} {qr.title}", callback_data=f"admin_saved_qr:{qr.id}")
    builder.button(text="➕ Добавить QR", callback_data="admin_saved_qr_add")
    builder.button(text="Назад", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()


def admin_saved_qr_detail_kb(qr_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Изменить название", callback_data=f"admin_saved_qr_edit_title:{qr_id}")
    builder.button(text="Изменить QR", callback_data=f"admin_saved_qr_edit_photo:{qr_id}")
    builder.button(text="Удалить QR", callback_data=f"admin_saved_qr_delete:{qr_id}")
    builder.button(text="К списку QR", callback_data="admin_saved_qrs")
    builder.adjust(1)
    return builder.as_markup()


def admin_saved_qr_apply_list_kb(promotion_id: int, qr_codes: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for qr in qr_codes:
        builder.button(text=f"{qr.title}", callback_data=f"admin_qr_template_apply:{promotion_id}:{qr.id}")
    builder.button(text="⬅️ Назад", callback_data=f"admin_promo_qr_list:{promotion_id}")
    builder.adjust(1)
    return builder.as_markup()


def admin_skip_photo_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Пропустить фото", callback_data="admin_promo_skip_photo")
    builder.button(text="Отмена", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()

def admin_payment_text_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Сбросить на дефолтный", callback_data="admin_promo_payment_text_default")
    builder.button(text="Отмена", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()

def admin_cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()


def admin_payment_instruction_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Установить дефолтный текст", callback_data="admin_payment_instruction_default")
    builder.button(text="Отмена", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()


def admin_bank_choice_text_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Установить дефолтный текст", callback_data="admin_bank_choice_text_default")
    builder.button(text="Назад", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()


def admin_stickers_text_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Установить дефолтный текст", callback_data="admin_stickers_text_default")
    builder.button(text="Назад", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()


def admin_payment_manager_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()


def support_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ Написать в поддержку", callback_data="write_support")
    builder.button(text="⬅️ Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()

def _sticker_width_icon(row_width: int) -> str:
    return "↔" if row_width == 2 else "▦"


def sticker_buttons_kb(buttons: list) -> InlineKeyboardMarkup:
    """Динамические кнопки стикеров из БД."""
    rows: list[list[InlineKeyboardButton]] = []
    pending_row: list[InlineKeyboardButton] = []

    for btn in buttons:
        keyboard_button = InlineKeyboardButton(text=btn.label, callback_data=f"stickers_btn:{btn.id}")
        if getattr(btn, "row_width", 1) == 2:
            if pending_row:
                rows.append(pending_row)
                pending_row = []
            rows.append([keyboard_button])
            continue

        pending_row.append(keyboard_button)
        if len(pending_row) == 2:
            rows.append(pending_row)
            pending_row = []

    if pending_row:
        rows.append(pending_row)

    rows.append([InlineKeyboardButton(text="🔢 Другое кол-во стикеров", callback_data="stickers_custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_sticker_buttons_kb(promotion_id: int, buttons: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for btn in buttons:
        builder.button(
            text=f"✏️ {btn.label} ({btn.sticker_count} шт., {_sticker_width_icon(getattr(btn, 'row_width', 1))})",
            callback_data=f"admin_btn_edit:{btn.id}:{promotion_id}"
    )
    builder.button(text="➕ Добавить кнопку", callback_data=f"admin_btn_add:{promotion_id}")
    builder.button(text="⚡ Стандартные 1 / 2 / 3 / 5+1 / 10+2", callback_data=f"admin_btn_defaults:{promotion_id}")
    builder.button(text="📂 Выбрать шаблон вариантов покупки", callback_data=f"admin_btn_config_apply_list:{promotion_id}")
    builder.button(text="⬅️ Назад", callback_data=f"admin_promo:{promotion_id}")
    builder.adjust(1)
    return builder.as_markup()


def admin_btn_edit_kb(btn_id: int, promotion_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить текст", callback_data=f"admin_btn_edit_label:{btn_id}:{promotion_id}")
    builder.button(text="🔢 Изменить кол-во", callback_data=f"admin_btn_edit_count:{btn_id}:{promotion_id}")
    builder.button(text="⬆️ Выше", callback_data=f"admin_btn_move:{btn_id}:{promotion_id}:-1")
    builder.button(text="⬇️ Ниже", callback_data=f"admin_btn_move:{btn_id}:{promotion_id}:1")
    builder.button(text="↔️ Переключить ширину", callback_data=f"admin_btn_toggle_width:{btn_id}:{promotion_id}")
    builder.button(text="🗑 Удалить", callback_data=f"admin_btn_delete:{btn_id}:{promotion_id}")
    builder.button(text="⬅️ Назад", callback_data=f"admin_btn_list:{promotion_id}")
    builder.adjust(1, 1, 2, 1, 1, 1)
    return builder.as_markup()


def admin_button_configs_kb(configs: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for config in configs:
        builder.button(
            text=f"#{config.id} {config.title} ({len(config.buttons)} кноп.)",
            callback_data=f"admin_btn_config:{config.id}",
        )
    builder.button(text="➕ Создать шаблон", callback_data="admin_btn_config_add")
    builder.button(text="Назад", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()


def admin_button_config_detail_kb(config_id: int, buttons: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for btn in buttons:
        builder.button(
            text=f"✏️ {btn.label} ({btn.sticker_count} шт., {_sticker_width_icon(getattr(btn, 'row_width', 1))})",
            callback_data=f"admin_btn_config_btn:{btn.id}:{config_id}",
    )
    builder.button(text="➕ Добавить кнопку", callback_data=f"admin_btn_config_btn_add:{config_id}")
    builder.button(text="Изменить название", callback_data=f"admin_btn_config_edit_title:{config_id}")
    builder.button(text="Удалить шаблон", callback_data=f"admin_btn_config_delete:{config_id}")
    builder.button(text="К списку шаблонов", callback_data="admin_btn_configs")
    builder.adjust(1)
    return builder.as_markup()


def admin_button_config_button_edit_kb(button_id: int, config_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить текст", callback_data=f"admin_btn_config_btn_edit_label:{button_id}:{config_id}")
    builder.button(text="🔢 Изменить кол-во", callback_data=f"admin_btn_config_btn_edit_count:{button_id}:{config_id}")
    builder.button(text="⬆️ Выше", callback_data=f"admin_btn_config_btn_move:{button_id}:{config_id}:-1")
    builder.button(text="⬇️ Ниже", callback_data=f"admin_btn_config_btn_move:{button_id}:{config_id}:1")
    builder.button(text="↔️ Переключить ширину", callback_data=f"admin_btn_config_btn_toggle_width:{button_id}:{config_id}")
    builder.button(text="🗑 Удалить", callback_data=f"admin_btn_config_btn_delete:{button_id}:{config_id}")
    builder.button(text="⬅️ Назад", callback_data=f"admin_btn_config:{config_id}")
    builder.adjust(1, 1, 2, 1, 1, 1)
    return builder.as_markup()


def admin_button_config_apply_list_kb(promotion_id: int, configs: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for config in configs:
        builder.button(
            text=f"{config.title} ({len(config.buttons)} кноп.)",
            callback_data=f"admin_btn_config_apply:{promotion_id}:{config.id}",
        )
    builder.button(text="⬅️ Назад", callback_data=f"admin_btn_list:{promotion_id}")
    builder.adjust(1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Admin UI v2
# These definitions intentionally replace the legacy keyboards above while
# keeping callback names compatible with existing handlers.

def admin_panel_kb(main_menu_photo_exists: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🎁 Акции", callback_data="admin_promos")
    builder.button(text="🧩 Шаблоны вариантов покупки", callback_data="admin_btn_configs")
    builder.button(text="📷 Библиотека QR-кодов", callback_data="admin_saved_qrs")
    builder.button(text="📝 Тексты и контакты оплаты", callback_data="admin_payment_settings")
    builder.button(text="🖼 Главное меню", callback_data="admin_content")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="❓ Помощь", callback_data="admin_help")
    builder.adjust(1, 1, 1, 1, 2, 1)
    return builder.as_markup()


def admin_content_kb(main_menu_photo_exists: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Приветственный текст", callback_data="admin_edit_welcome")
    builder.button(text="🔘 Название кнопки участия", callback_data="admin_edit_join_button")
    builder.button(text="⚠️ Предупреждение о сторонних ссылках", callback_data="admin_edit_warning_text")
    builder.button(
        text="🗑 Удалить фото" if main_menu_photo_exists else "🖼 Добавить фото",
        callback_data="admin_main_menu_photo_delete" if main_menu_photo_exists else "admin_main_menu_photo_add",
    )
    builder.button(text="⬅️ Вернуться назад", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()


def admin_payment_settings_kb(qr_auto_delete_hours: int = 24) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Общая инструкция", callback_data="admin_edit_payment_instruction")
    builder.button(text="🏦 Текст выбора способа", callback_data="admin_edit_bank_choice_text")
    builder.button(text="🧾 Менеджер для чеков", callback_data="admin_edit_payment_manager")
    builder.button(text="🔘 Кнопки после оплаты", callback_data="admin_post_payment_settings")
    auto_delete_label = (
        "🕒 Автоудаление QR: выключено"
        if qr_auto_delete_hours == 0
        else f"🕒 Автоудаление QR: {qr_auto_delete_hours} ч"
    )
    builder.button(text=auto_delete_label, callback_data="admin_qr_auto_delete")
    builder.button(text="⬅️ Вернуться назад", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()


def admin_users_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="📥 Выгрузить участников", callback_data="admin_export_participants")
    builder.button(text="📣 Рассылка", callback_data="admin_broadcast")
    builder.button(text="🚫 Бан / разбан", callback_data="admin_ban")
    builder.button(text="⬅️ Вернуться назад", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()


def admin_promotion_edit_kb(promotion_id: int, is_active: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⏸ Деактивировать" if is_active else "✅ Опубликовать",
        callback_data=(
            f"admin_promo_deactivate:{promotion_id}"
            if is_active
            else f"admin_promo_activate:{promotion_id}"
        ),
    )
    builder.button(text="1️⃣ Варианты покупки: 1 / 2 / 5+1", callback_data=f"admin_btn_list:{promotion_id}")
    builder.button(text="2️⃣ Банки, QR и ссылки на оплату", callback_data=f"admin_promo_qr_list:{promotion_id}")
    builder.button(text="✏️ Название", callback_data=f"admin_promo_edit_title:{promotion_id}")
    builder.button(text="👁 Название для пользователей", callback_data=f"admin_promo_edit_prize:{promotion_id}")
    builder.button(text="🖼 Фото", callback_data=f"admin_promo_edit_photo:{promotion_id}")
    builder.button(text="💰 Цена", callback_data=f"admin_promo_edit_price:{promotion_id}")
    builder.button(text="📝 Описание", callback_data=f"admin_promo_edit_desc:{promotion_id}")
    builder.button(text="📄 Инструкция к оплате", callback_data=f"admin_promo_edit_payment_text:{promotion_id}")
    builder.button(text="⬅️ Вернуться к акциям", callback_data="admin_promos")
    builder.button(text="🏠 В админ-панель", callback_data="admin_back")
    builder.button(text="🗑 Удалить акцию", callback_data=f"admin_promo_delete:{promotion_id}")
    builder.adjust(1, 2, 2, 2, 1, 1, 1, 1)
    return builder.as_markup()


def admin_qr_list_kb(promotion_id: int, qr_codes: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for method in qr_codes:
        icon = "🔗" if getattr(method, "method_type", "qr") == "link" else "📷"
        builder.button(
            text=f"{icon} {method.title}",
            callback_data=f"admin_payment_method:{method.id}:{promotion_id}",
        )
    builder.button(text="➕ Добавить способ оплаты", callback_data=f"admin_payment_method_add:{promotion_id}")
    builder.button(text="📂 Добавить QR из библиотеки", callback_data=f"admin_qr_template_list:{promotion_id}")
    if qr_codes:
        builder.button(text="🗑 Удалить все способы из акции", callback_data=f"admin_qr_delete_all_confirm:{promotion_id}")
    builder.button(text="⬅️ Вернуться к акции", callback_data=f"admin_promo:{promotion_id}")
    builder.adjust(1)
    return builder.as_markup()


def admin_payment_method_type_kb(promotion_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📷 QR-код", callback_data=f"admin_payment_method_type:qr:{promotion_id}")
    builder.button(text="🔗 Ссылка на оплату", callback_data=f"admin_payment_method_type:link:{promotion_id}")
    builder.button(text="⬅️ Вернуться назад", callback_data=f"admin_promo_qr_list:{promotion_id}")
    builder.adjust(1)
    return builder.as_markup()


def admin_payment_method_detail_kb(
    method_id: int,
    promotion_id: int,
    method_type: str = "qr",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✏️ Изменить название банка/способа",
        callback_data=f"admin_payment_method_edit_title:{method_id}:{promotion_id}",
    )
    content_label = "🔗 Изменить ссылку" if method_type == "link" else "🖼 Заменить QR-код"
    builder.button(
        text=content_label,
        callback_data=f"admin_payment_method_edit_content:{method_id}:{promotion_id}",
    )
    builder.button(text="🗑 Удалить способ", callback_data=f"admin_qr_delete:{method_id}:{promotion_id}")
    builder.button(text="⬅️ Вернуться назад", callback_data=f"admin_promo_qr_list:{promotion_id}")
    builder.adjust(1)
    return builder.as_markup()


def payment_result_kb(
    manager_username: str,
    payment_url: str | None = None,
    *,
    send_receipt_label: str = "🧾 ОТПРАВИТЬ ЧЕК МЕНЕДЖЕРУ ↗",
    show_send_receipt: bool = True,
    buy_again_label: str = "Купить ещё",
    show_buy_again: bool = True,
    how_to_pay_label: str = "Как оплатить ❓",
    show_how_to_pay: bool = True,
    where_number_label: str = "Где мой номер?",
    show_where_number: bool = True,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if payment_url:
        builder.button(text="💳 ПЕРЕЙТИ К ОПЛАТЕ ↗", url=payment_url)
    if show_send_receipt and manager_username:
        manager_url = f"https://t.me/{manager_username.lstrip('@')}"
        builder.button(text=send_receipt_label, url=manager_url)
    if show_buy_again:
        builder.button(text=buy_again_label, callback_data="buy_sticker")
    if show_how_to_pay:
        builder.button(text=how_to_pay_label, callback_data="how_to_pay")
    if show_where_number:
        builder.button(text=where_number_label, callback_data="where_number")
    builder.adjust(1)
    return builder.as_markup()


def admin_post_payment_settings_kb(values: dict[str, tuple[bool, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    titles = {
        "send_receipt": "Отправить чек менеджеру",
        "buy_again": "Купить ещё",
        "how_to_pay": "Как оплатить",
        "where_number": "Где мой номер",
    }
    for key, (enabled, _label) in values.items():
        mark = "✅" if enabled else "⛔"
        builder.button(
            text=f"{mark} {titles[key]}",
            callback_data=f"admin_post_payment_item:{key}",
        )
    builder.button(text="⬅️ Вернуться назад", callback_data="admin_payment_settings")
    builder.adjust(1)
    return builder.as_markup()


def admin_post_payment_item_kb(key: str, enabled: bool, has_text: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⛔ Выключить" if enabled else "✅ Включить",
        callback_data=f"admin_post_payment_toggle:{key}",
    )
    builder.button(text="✏️ Изменить название кнопки", callback_data=f"admin_post_payment_label:{key}")
    if has_text:
        builder.button(text="📝 Изменить сообщение", callback_data=f"admin_post_payment_text:{key}")
    builder.button(text="⬅️ Вернуться назад", callback_data="admin_post_payment_settings")
    builder.adjust(1)
    return builder.as_markup()


def admin_qr_delete_all_confirm_kb(promotion_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, удалить из акции", callback_data=f"admin_qr_delete_all:{promotion_id}")
    builder.button(text="⬅️ Вернуться назад", callback_data=f"admin_promo_qr_list:{promotion_id}")
    builder.adjust(1)
    return builder.as_markup()


def admin_promo_back_kb(promotion_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Вернуться назад", callback_data=f"admin_promo:{promotion_id}")
    builder.adjust(1)
    return builder.as_markup()


def admin_cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Вернуться назад", callback_data="admin_back")
    builder.adjust(1)
    return builder.as_markup()


def admin_payment_instruction_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="↩️ Вернуть стандартный текст", callback_data="admin_payment_instruction_default")
    builder.button(text="⬅️ Вернуться назад", callback_data="admin_payment_settings")
    builder.adjust(1)
    return builder.as_markup()


def admin_bank_choice_text_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="↩️ Вернуть стандартный текст", callback_data="admin_bank_choice_text_default")
    builder.button(text="⬅️ Вернуться назад", callback_data="admin_payment_settings")
    builder.adjust(1)
    return builder.as_markup()


def admin_payment_manager_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Вернуться назад", callback_data="admin_payment_settings")
    builder.adjust(1)
    return builder.as_markup()
