from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from sqlalchemy import select

from portrait_bot.context import AppContext
from portrait_bot.models import AuditLog, BotSetting, StoreOrder, StoreProfile, User
from portrait_bot.money import format_rub
from portrait_bot.services import get_or_create_user

router = Router(name="storefront")


class StoreProfileFlow(StatesGroup):
    awaiting_phone = State()
    awaiting_full_name = State()
    awaiting_city = State()


class StorePaymentFlow(StatesGroup):
    awaiting_proof = State()


class StoreAdminFlow(StatesGroup):
    awaiting_value = State()
    awaiting_qr = State()
    awaiting_campaign_image = State()


STORE_SETTINGS: dict[str, tuple[str, str]] = {
    "gateway_message": (
        "Текст выбора раздела",
        "Выберите, что хотите сделать:",
    ),
    "gateway_store_button": (
        "Кнопка магазина на старте",
        "📱 Купить стикер «iPhone 17»",
    ),
    "gateway_ai_button": (
        "Кнопка AI-генерации на старте",
        "✨ AI-генерация изображений",
    ),
    "store_enabled": ("Магазин включён", "true"),
    "store_campaign_title": ("Название акции", "Стикер «iPhone 17»"),
    "store_campaign_description": (
        "Описание акции",
        "Выберите количество стикеров. Покупка стикера даёт право участвовать "
        "в действующей стимулирующей акции на опубликованных условиях.",
    ),
    "store_packages": (
        "Варианты покупки",
        "1:99,5:450,10:800",
    ),
    "store_payment_instruction": (
        "Инструкция по оплате",
        "Оплатите выбранную сумму, затем нажмите «Я оплатил» и отправьте чек.",
    ),
    "store_payment_url": ("Ссылка для оплаты", ""),
    "store_qr_file_id": ("QR-код магазина", ""),
    "store_campaign_image_file_id": ("Картинка акции", ""),
}


async def seed_storefront_settings(context: AppContext) -> None:
    async with context.db.sessions() as session:
        existing = set(
            (
                await session.scalars(
                    select(BotSetting.key).where(BotSetting.key.in_(STORE_SETTINGS))
                )
            ).all()
        )
        for key, (title, default) in STORE_SETTINGS.items():
            if key not in existing:
                session.add(BotSetting(key=key, title=title, value=default))
        await session.commit()


async def store_settings(context: AppContext) -> dict[str, str]:
    async with context.db.sessions() as session:
        rows = list(
            (
                await session.scalars(select(BotSetting).where(BotSetting.key.in_(STORE_SETTINGS)))
            ).all()
        )
    values = {key: default for key, (_, default) in STORE_SETTINGS.items()}
    values.update({row.key: row.value for row in rows})
    return values


def parse_store_packages(raw: str) -> list[tuple[int, Decimal]]:
    packages: list[tuple[int, Decimal]] = []
    seen: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":", 1)
        if len(parts) != 2:
            raise ValueError("Каждый вариант должен иметь формат КОЛИЧЕСТВО:ЦЕНА")
        try:
            quantity = int(parts[0].strip())
            price = Decimal(parts[1].strip().replace(" ", "").replace(",", "."))
        except (ValueError, InvalidOperation) as error:
            raise ValueError("Количество и цена должны быть числами") from error
        if quantity < 1 or quantity > 1000:
            raise ValueError("Количество должно быть от 1 до 1000")
        if price < 1 or price > Decimal("1000000"):
            raise ValueError("Цена должна быть от 1 до 1 000 000 рублей")
        if quantity in seen:
            raise ValueError("Количество в вариантах не должно повторяться")
        seen.add(quantity)
        packages.append((quantity, price.quantize(Decimal("0.01"))))
    if not packages:
        raise ValueError("Добавьте хотя бы один вариант покупки")
    return packages


def gateway_menu(values: dict[str, str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if values.get("store_enabled", "true").lower() in {"1", "true", "yes", "on"}:
        rows.append(
            [
                InlineKeyboardButton(
                    text=values["gateway_store_button"],
                    callback_data="entry:store",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=values["gateway_ai_button"],
                callback_data="entry:ai",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _store_home_keyboard(values: dict[str, str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for quantity, amount in parse_store_packages(values["store_packages"]):
        noun = "стикер" if quantity == 1 else "стикеров"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{quantity} {noun} — {format_rub(amount)}",
                    callback_data=f"store:buy:{quantity}",
                )
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text="🧾 Мои покупки", callback_data="store:orders")],
            [InlineKeyboardButton(text="◀️ Выбор раздела", callback_data="menu:gateway")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _payment_keyboard(order_id: str, payment_url: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if payment_url:
        rows.append([InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)])
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="✅ Я оплатил — отправить чек",
                    callback_data=f"store:paid:{order_id}",
                )
            ],
            [InlineKeyboardButton(text="◀️ Назад к акции", callback_data="store:home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _admin_review_keyboard(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"admin:store:approve:{order_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"admin:store:reject:{order_id}",
                ),
            ]
        ]
    )


def store_admin_menu(values: dict[str, str]) -> InlineKeyboardMarkup:
    enabled = values.get("store_enabled", "true").lower() in {"1", "true", "yes", "on"}
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{'🟢' if enabled else '⚪️'} Магазин на стартовом экране",
                    callback_data="admin:store:toggle",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Кнопка магазина",
                    callback_data="admin:store:edit:gateway_store_button",
                ),
                InlineKeyboardButton(
                    text="✏️ Кнопка AI",
                    callback_data="admin:store:edit:gateway_ai_button",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📝 Текст выбора раздела",
                    callback_data="admin:store:edit:gateway_message",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏷 Название акции",
                    callback_data="admin:store:edit:store_campaign_title",
                ),
                InlineKeyboardButton(
                    text="📋 Описание акции",
                    callback_data="admin:store:edit:store_campaign_description",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💰 Варианты и цены",
                    callback_data="admin:store:edit:store_packages",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💳 Инструкция по оплате",
                    callback_data="admin:store:edit:store_payment_instruction",
                ),
                InlineKeyboardButton(
                    text="🔗 Ссылка оплаты",
                    callback_data="admin:store:edit:store_payment_url",
                ),
            ],
            [
                InlineKeyboardButton(text="🖼 Картинка акции", callback_data="admin:store:image"),
                InlineKeyboardButton(text="📷 QR-код", callback_data="admin:store:qr"),
            ],
            [
                InlineKeyboardButton(
                    text="🧾 Заявки на оплату",
                    callback_data="admin:store:orders",
                )
            ],
            [InlineKeyboardButton(text="◀️ Админ-панель", callback_data="admin:main")],
        ]
    )


async def _current_user(message: Message, context: AppContext) -> User:
    async with context.db.sessions() as session:
        return await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            language_code=message.from_user.language_code,
        )


async def _profile_for(context: AppContext, user_id: str) -> StoreProfile | None:
    async with context.db.sessions() as session:
        return await session.scalar(select(StoreProfile).where(StoreProfile.user_id == user_id))


async def _begin_store_profile(message: Message, state: FSMContext) -> None:
    await state.set_state(StoreProfileFlow.awaiting_phone)
    await message.answer(
        "Для оформления покупки один раз заполните данные участника.\n\n"
        "Отправьте номер телефона кнопкой ниже или введите его сообщением.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


async def send_store_home(message: Message, context: AppContext) -> None:
    values = await store_settings(context)
    if values.get("store_enabled", "true").lower() not in {"1", "true", "yes", "on"}:
        await message.answer(
            "Раздел покупки стикеров временно недоступен.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Выбор раздела", callback_data="menu:gateway")]
                ]
            ),
        )
        return
    text = (
        f"<b>{escape(values['store_campaign_title'])}</b>\n\n"
        f"{escape(values['store_campaign_description'])}\n\n"
        "Выберите вариант покупки:"
    )
    markup = _store_home_keyboard(values)
    image = values.get("store_campaign_image_file_id", "")
    if image:
        await message.answer_photo(image, caption=text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "entry:store")
async def enter_store(callback: CallbackQuery, state: FSMContext, context: AppContext) -> None:
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    await callback.answer()
    async with context.db.sessions() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            language_code=callback.from_user.language_code,
        )
        profile = await session.scalar(select(StoreProfile).where(StoreProfile.user_id == user.id))
    if profile is None:
        await state.update_data(store_user_id=user.id)
        await _begin_store_profile(callback.message, state)
        return
    await state.clear()
    await send_store_home(callback.message, context)


@router.message(StoreProfileFlow.awaiting_phone, F.contact)
async def store_phone_contact(message: Message, state: FSMContext) -> None:
    if not message.contact or message.contact.user_id not in {None, message.from_user.id}:
        await message.answer("Отправьте, пожалуйста, собственный номер телефона.")
        return
    await state.update_data(store_phone=message.contact.phone_number)
    await state.set_state(StoreProfileFlow.awaiting_full_name)
    await message.answer(
        "Введите фамилию, имя и отчество участника:",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(StoreProfileFlow.awaiting_phone, F.text)
async def store_phone_text(message: Message, state: FSMContext) -> None:
    phone = re.sub(r"[^0-9+]", "", message.text or "")
    if len(re.sub(r"\D", "", phone)) < 10:
        await message.answer("Введите номер полностью, например +7 999 123-45-67.")
        return
    await state.update_data(store_phone=phone)
    await state.set_state(StoreProfileFlow.awaiting_full_name)
    await message.answer(
        "Введите фамилию, имя и отчество участника:",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(StoreProfileFlow.awaiting_full_name, F.text)
async def store_full_name(message: Message, state: FSMContext) -> None:
    full_name = " ".join((message.text or "").split())
    if len(full_name) < 5:
        await message.answer("Укажите полное имя участника.")
        return
    await state.update_data(store_full_name=full_name)
    await state.set_state(StoreProfileFlow.awaiting_city)
    await message.answer("Укажите город проживания:")


@router.message(StoreProfileFlow.awaiting_city, F.text)
async def store_city(message: Message, state: FSMContext, context: AppContext) -> None:
    city = " ".join((message.text or "").split())
    if len(city) < 2:
        await message.answer("Укажите название города.")
        return
    data = await state.get_data()
    user_id = str(data.get("store_user_id") or "")
    async with context.db.sessions() as session:
        profile = await session.scalar(select(StoreProfile).where(StoreProfile.user_id == user_id))
        if profile:
            profile.phone = str(data.get("store_phone") or "")
            profile.full_name = str(data.get("store_full_name") or "")
            profile.city = city
        else:
            session.add(
                StoreProfile(
                    user_id=user_id,
                    phone=str(data.get("store_phone") or ""),
                    full_name=str(data.get("store_full_name") or ""),
                    city=city,
                )
            )
        await session.commit()
    await state.clear()
    await message.answer("Данные сохранены ✅", reply_markup=ReplyKeyboardRemove())
    await send_store_home(message, context)


@router.callback_query(F.data == "store:home")
async def store_home(callback: CallbackQuery, context: AppContext) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await send_store_home(callback.message, context)


@router.callback_query(F.data.startswith("store:buy:"))
async def store_buy(callback: CallbackQuery, context: AppContext) -> None:
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    try:
        quantity = int((callback.data or "").rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный вариант", show_alert=True)
        return
    values = await store_settings(context)
    packages = dict(parse_store_packages(values["store_packages"]))
    amount = packages.get(quantity)
    if amount is None:
        await callback.answer("Этот вариант больше недоступен", show_alert=True)
        return
    async with context.db.sessions() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        if user is None:
            await callback.answer("Нажмите /start и повторите", show_alert=True)
            return
        order = StoreOrder(
            user_id=user.id,
            campaign_title=values["store_campaign_title"],
            quantity=quantity,
            amount_rub=amount,
            status="created",
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
    await callback.answer()
    payment_text = (
        f"<b>Заказ {order.id[:8]}</b>\n"
        f"{escape(order.campaign_title)}\n"
        f"Количество: <b>{order.quantity}</b>\n"
        f"К оплате: <b>{format_rub(order.amount_rub)}</b>\n\n"
        f"{escape(values['store_payment_instruction'])}"
    )
    markup = _payment_keyboard(order.id, values.get("store_payment_url", ""))
    qr = values.get("store_qr_file_id", "")
    if qr:
        await callback.message.answer_photo(qr, caption=payment_text, reply_markup=markup)
    else:
        await callback.message.answer(payment_text, reply_markup=markup)


@router.callback_query(F.data.startswith("store:paid:"))
async def store_paid(callback: CallbackQuery, state: FSMContext, context: AppContext) -> None:
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    order_id = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        order = await session.get(StoreOrder, order_id)
        user = await session.get(User, order.user_id) if order else None
    if not order or not user or user.telegram_id != callback.from_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    await state.set_state(StorePaymentFlow.awaiting_proof)
    await state.update_data(store_order_id=order.id)
    await callback.answer()
    await callback.message.answer("Отправьте чек одним сообщением — фотографией или файлом.")


@router.message(StorePaymentFlow.awaiting_proof, F.photo | F.document)
async def store_payment_proof(
    message: Message,
    state: FSMContext,
    context: AppContext,
    bot: Bot,
) -> None:
    data = await state.get_data()
    order_id = str(data.get("store_order_id") or "")
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    file_type = "photo" if message.photo else "document"
    async with context.db.sessions() as session:
        order = await session.get(StoreOrder, order_id)
        if not order:
            await state.clear()
            await message.answer("Заказ не найден.")
            return
        order.proof_file_id = file_id
        order.proof_file_type = file_type
        order.status = "submitted"
        user = await session.get(User, order.user_id)
        profile = await session.scalar(
            select(StoreProfile).where(StoreProfile.user_id == order.user_id)
        )
        await session.commit()
    await state.clear()
    await message.answer(
        f"Чек по заказу <code>{order.id[:8]}</code> отправлен администратору ✅\n"
        "После проверки вы получите сообщение в этом чате."
    )
    admin_text = (
        f"🧾 <b>Новая оплата магазина</b>\n"
        f"Заказ: <code>{order.id[:8]}</code>\n"
        f"Акция: {escape(order.campaign_title)}\n"
        f"Количество: <b>{order.quantity}</b>\n"
        f"Сумма: <b>{format_rub(order.amount_rub)}</b>\n"
        f"Пользователь: @{escape(user.username or '—')} / <code>{user.telegram_id}</code>"
    )
    if profile:
        admin_text += (
            f"\nФИО: {escape(profile.full_name)}"
            f"\nТелефон: {escape(profile.phone)}"
            f"\nГород: {escape(profile.city)}"
        )
    for admin_id in context.settings.admin_ids:
        try:
            if file_type == "photo":
                await bot.send_photo(
                    admin_id,
                    file_id,
                    caption=admin_text,
                    reply_markup=_admin_review_keyboard(order.id),
                )
            else:
                await bot.send_document(
                    admin_id,
                    file_id,
                    caption=admin_text,
                    reply_markup=_admin_review_keyboard(order.id),
                )
        except Exception:
            continue


@router.message(StorePaymentFlow.awaiting_proof)
async def store_payment_proof_invalid(message: Message) -> None:
    await message.answer("Отправьте фотографию чека или файл.")


@router.callback_query(F.data == "store:orders")
async def store_orders(callback: CallbackQuery, context: AppContext) -> None:
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    async with context.db.sessions() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        orders = (
            list(
                (
                    await session.scalars(
                        select(StoreOrder)
                        .where(StoreOrder.user_id == user.id)
                        .order_by(StoreOrder.created_at.desc())
                        .limit(10)
                    )
                ).all()
            )
            if user
            else []
        )
    await callback.answer()
    labels = {
        "created": "ожидает оплаты",
        "submitted": "чек на проверке",
        "paid": "оплачен",
        "rejected": "отклонён",
    }
    if not orders:
        await callback.message.answer("Покупок пока нет.")
        return
    lines = ["<b>Последние покупки</b>"]
    for order in orders:
        lines.append(
            f"\n<code>{order.id[:8]}</code> · {order.quantity} шт. · "
            f"{format_rub(order.amount_rub)} · {labels.get(order.status, order.status)}"
        )
    await callback.message.answer("".join(lines))


async def _review_order(
    callback: CallbackQuery,
    context: AppContext,
    *,
    approved: bool,
) -> None:
    if not callback.from_user or callback.from_user.id not in context.settings.admin_ids:
        await callback.answer("Недоступно", show_alert=True)
        return
    order_id = (callback.data or "").rsplit(":", 1)[1]
    async with context.db.sessions() as session:
        order = await session.get(StoreOrder, order_id)
        if not order:
            await callback.answer("Заказ не найден", show_alert=True)
            return
        if order.status in {"paid", "rejected"}:
            await callback.answer("Заказ уже обработан", show_alert=True)
            return
        order.status = "paid" if approved else "rejected"
        order.reviewed_by = callback.from_user.id
        order.reviewed_at = datetime.now(UTC)
        user = await session.get(User, order.user_id)
        session.add(
            AuditLog(
                actor_telegram_id=callback.from_user.id,
                action="store_order_approved" if approved else "store_order_rejected",
                target_type="store_order",
                target_id=order.id,
            )
        )
        await session.commit()
    await callback.answer("Оплата подтверждена" if approved else "Оплата отклонена")
    if user:
        await context.bot.send_message(
            user.telegram_id,
            (
                f"Оплата заказа <code>{order.id[:8]}</code> подтверждена ✅"
                if approved
                else f"Оплата заказа <code>{order.id[:8]}</code> отклонена. Напишите в поддержку."
            ),
        )
    if isinstance(callback.message, Message):
        marker = "\n\n✅ <b>ПОДТВЕРЖДЕНО</b>" if approved else "\n\n❌ <b>ОТКЛОНЕНО</b>"
        if callback.message.caption:
            await callback.message.edit_caption(caption=callback.message.caption + marker)
        elif callback.message.text:
            await callback.message.edit_text(callback.message.text + marker)


@router.callback_query(F.data.startswith("admin:store:approve:"))
async def store_order_approve(callback: CallbackQuery, context: AppContext) -> None:
    await _review_order(callback, context, approved=True)


@router.callback_query(F.data.startswith("admin:store:reject:"))
async def store_order_reject(callback: CallbackQuery, context: AppContext) -> None:
    await _review_order(callback, context, approved=False)


@router.callback_query(F.data == "admin:store")
async def admin_store(callback: CallbackQuery, context: AppContext) -> None:
    if not callback.from_user or callback.from_user.id not in context.settings.admin_ids:
        await callback.answer("Недоступно", show_alert=True)
        return
    values = await store_settings(context)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "<b>Магазин и стартовый экран</b>\n\n"
            "Здесь настраиваются две первые кнопки, акция, цены и приём чеков.",
            reply_markup=store_admin_menu(values),
        )


@router.callback_query(F.data == "admin:store:toggle")
async def admin_store_toggle(callback: CallbackQuery, context: AppContext) -> None:
    if not callback.from_user or callback.from_user.id not in context.settings.admin_ids:
        await callback.answer("Недоступно", show_alert=True)
        return
    values = await store_settings(context)
    enabled = values.get("store_enabled", "true").lower() in {"1", "true", "yes", "on"}
    async with context.db.sessions() as session:
        setting = await session.get(BotSetting, "store_enabled")
        setting.value = "false" if enabled else "true"
        await session.commit()
    await callback.answer("Настройка сохранена")
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Магазин включён." if not enabled else "Магазин скрыт со стартового экрана.",
            reply_markup=store_admin_menu(await store_settings(context)),
        )


@router.callback_query(F.data.startswith("admin:store:edit:"))
async def admin_store_edit(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not callback.from_user or callback.from_user.id not in context.settings.admin_ids:
        await callback.answer("Недоступно", show_alert=True)
        return
    key = (callback.data or "").split("admin:store:edit:", 1)[1]
    if key not in STORE_SETTINGS or key in {
        "store_enabled",
        "store_qr_file_id",
        "store_campaign_image_file_id",
    }:
        await callback.answer("Настройка не найдена", show_alert=True)
        return
    values = await store_settings(context)
    await state.set_state(StoreAdminFlow.awaiting_value)
    await state.update_data(store_setting_key=key)
    await callback.answer()
    hint = ""
    if key == "store_packages":
        hint = "\n\nФормат: <code>1:99,5:450,10:800</code>"
    elif key == "store_payment_url":
        hint = "\n\nОтправьте <code>-</code>, чтобы удалить ссылку."
    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"<b>{STORE_SETTINGS[key][0]}</b>\n\nСейчас:\n{escape(values[key])}"
            f"{hint}\n\nОтправьте новое значение одним сообщением."
        )


@router.message(StoreAdminFlow.awaiting_value, F.text)
async def admin_store_save(
    message: Message,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        return
    data = await state.get_data()
    key = str(data.get("store_setting_key") or "")
    raw = (message.text or "").strip()
    if key not in STORE_SETTINGS:
        await state.clear()
        await message.answer("Настройка не найдена.")
        return
    if key == "store_packages":
        try:
            parse_store_packages(raw)
        except ValueError as error:
            await message.answer(str(error))
            return
    elif key == "store_payment_url":
        if raw in {"-", "нет", "удалить"}:
            raw = ""
        elif raw and not raw.startswith("https://"):
            await message.answer("Ссылка должна начинаться с https://")
            return
    elif not 2 <= len(raw) <= 3500:
        await message.answer("Значение должно содержать от 2 до 3500 символов.")
        return
    async with context.db.sessions() as session:
        setting = await session.get(BotSetting, key)
        if setting:
            setting.value = raw
        else:
            session.add(BotSetting(key=key, title=STORE_SETTINGS[key][0], value=raw))
        session.add(
            AuditLog(
                actor_telegram_id=message.from_user.id,
                action="store_setting_edit",
                target_type="bot_setting",
                target_id=key,
            )
        )
        await session.commit()
    await state.clear()
    await message.answer(
        "Настройка сохранена ✅",
        reply_markup=store_admin_menu(await store_settings(context)),
    )


async def _begin_image_upload(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
    *,
    state_value: State,
    title: str,
) -> None:
    if not callback.from_user or callback.from_user.id not in context.settings.admin_ids:
        await callback.answer("Недоступно", show_alert=True)
        return
    await state.set_state(state_value)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(f"<b>{title}</b>\n\nОтправьте новую картинку как фотографию.")


@router.callback_query(F.data == "admin:store:qr")
async def admin_store_qr(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    await _begin_image_upload(
        callback,
        state,
        context,
        state_value=StoreAdminFlow.awaiting_qr,
        title="QR-код магазина",
    )


@router.callback_query(F.data == "admin:store:image")
async def admin_store_image(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    await _begin_image_upload(
        callback,
        state,
        context,
        state_value=StoreAdminFlow.awaiting_campaign_image,
        title="Картинка акции",
    )


async def _save_store_image(
    message: Message,
    state: FSMContext,
    context: AppContext,
    *,
    key: str,
) -> None:
    if not message.from_user or message.from_user.id not in context.settings.admin_ids:
        return
    file_id = message.photo[-1].file_id
    async with context.db.sessions() as session:
        setting = await session.get(BotSetting, key)
        if setting:
            setting.value = file_id
        else:
            session.add(BotSetting(key=key, title=STORE_SETTINGS[key][0], value=file_id))
        await session.commit()
    await state.clear()
    await message.answer_photo(
        file_id,
        caption="Картинка сохранена ✅",
        reply_markup=store_admin_menu(await store_settings(context)),
    )


@router.message(StoreAdminFlow.awaiting_qr, F.photo)
async def admin_store_qr_save(
    message: Message,
    state: FSMContext,
    context: AppContext,
) -> None:
    await _save_store_image(message, state, context, key="store_qr_file_id")


@router.message(StoreAdminFlow.awaiting_campaign_image, F.photo)
async def admin_store_image_save(
    message: Message,
    state: FSMContext,
    context: AppContext,
) -> None:
    await _save_store_image(message, state, context, key="store_campaign_image_file_id")


@router.callback_query(F.data == "admin:store:orders")
async def admin_store_orders(callback: CallbackQuery, context: AppContext) -> None:
    if not callback.from_user or callback.from_user.id not in context.settings.admin_ids:
        await callback.answer("Недоступно", show_alert=True)
        return
    async with context.db.sessions() as session:
        orders = list(
            (
                await session.scalars(
                    select(StoreOrder)
                    .where(StoreOrder.status == "submitted")
                    .order_by(StoreOrder.created_at.asc())
                    .limit(20)
                )
            ).all()
        )
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if not orders:
        await callback.message.answer(
            "Непроверенных оплат нет.",
            reply_markup=store_admin_menu(await store_settings(context)),
        )
        return
    await callback.message.answer(
        "<b>Непроверенные оплаты</b>\n"
        + "\n".join(
            f"<code>{order.id[:8]}</code> · {order.quantity} шт. · {format_rub(order.amount_rub)}"
            for order in orders
        )
    )
