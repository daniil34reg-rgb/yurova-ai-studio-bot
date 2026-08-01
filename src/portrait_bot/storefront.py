from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings as store_runtime_settings
from bot.handlers.admin import _open_admin_panel as open_store_admin_panel
from bot.handlers.start import (
    NO_PROMO_TEXT,
    _main_menu_keyboard,
    _welcome_text,
)
from bot.repositories import PromotionRepository, SettingsRepository, UserRepository
from bot.services import UserService
from portrait_bot.context import AppContext
from portrait_bot.models import BotSetting

router = Router(name="gateway")


class GatewayAdminFlow(StatesGroup):
    awaiting_value = State()


GATEWAY_SETTINGS: dict[str, tuple[str, str]] = {
    "gateway_message": (
        "Текст выбора раздела",
        "Выберите, что хотите сделать:",
    ),
    "gateway_store_button": (
        "Первая кнопка на старте",
        "📱 Купить стикер «iPhone 17»",
    ),
    "gateway_ai_button": (
        "Вторая кнопка на старте",
        "✨ Генерация изображений",
    ),
}


async def seed_storefront_settings(context: AppContext) -> None:
    async with context.db.sessions() as session:
        existing = set(
            (
                await session.scalars(
                    select(BotSetting.key).where(BotSetting.key.in_(GATEWAY_SETTINGS))
                )
            ).all()
        )
        for key, (title, default) in GATEWAY_SETTINGS.items():
            if key not in existing:
                session.add(BotSetting(key=key, title=title, value=default))
        await session.commit()


async def store_settings(context: AppContext) -> dict[str, str]:
    async with context.db.sessions() as session:
        rows = list(
            (
                await session.scalars(
                    select(BotSetting).where(BotSetting.key.in_(GATEWAY_SETTINGS))
                )
            ).all()
        )
    values = {key: default for key, (_, default) in GATEWAY_SETTINGS.items()}
    values.update({row.key: row.value for row in rows})
    return values


def gateway_menu(values: dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=values["gateway_store_button"],
                    callback_data="entry:store",
                )
            ],
            [
                InlineKeyboardButton(
                    text=values["gateway_ai_button"],
                    callback_data="entry:ai",
                )
            ],
        ]
    )


def admin_root_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📱 Магазин и акции",
                    callback_data="admin:section:store",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✨ Генерация",
                    callback_data="admin:section:ai",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚪 Начальный экран",
                    callback_data="admin:gateway",
                )
            ],
        ]
    )


def gateway_admin_menu(values: dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Первая кнопка",
                    callback_data="admin:gateway:edit:gateway_store_button",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Вторая кнопка",
                    callback_data="admin:gateway:edit:gateway_ai_button",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Текст над кнопками",
                    callback_data="admin:gateway:edit:gateway_message",
                )
            ],
            [InlineKeyboardButton(text="◀️ Выбор админки", callback_data="admin:root")],
        ]
    )


def _is_admin(user_id: int | None, context: AppContext) -> bool:
    return bool(user_id and user_id in context.settings.admin_ids)


async def _send_admin_root(message: Message) -> None:
    await message.answer(
        "<b>Админ-панель</b>\n\nВыберите, какой частью бота управлять:",
        reply_markup=admin_root_menu(),
    )


@router.message(Command("admin"))
async def admin_root_command(message: Message, context: AppContext) -> None:
    if not message.from_user or not _is_admin(message.from_user.id, context):
        await message.answer("Команда недоступна.")
        return
    await _send_admin_root(message)


@router.callback_query(F.data.in_({"admin:root", "admin_open"}))
async def admin_root_callback(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not _is_admin(callback.from_user.id, context):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    if isinstance(callback.message, Message):
        await _send_admin_root(callback.message)


@router.callback_query(F.data == "entry:store")
async def enter_store(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Open the unchanged home screen of the full PayStickerBOT application."""
    if not isinstance(callback.message, Message):
        return
    await state.clear()
    await UserService(UserRepository(session)).register_or_update(callback.from_user)
    promotions = await PromotionRepository(session).get_all_active()
    keyboard = await _main_menu_keyboard(
        session,
        callback.from_user.id in store_runtime_settings.admin_ids,
    )
    await callback.answer()
    if not promotions:
        await callback.message.answer(NO_PROMO_TEXT, reply_markup=keyboard)
        return
    text = await _welcome_text(promotions, session)
    main_menu_photo = await SettingsRepository(session).get("main_menu_photo_file_id", "")
    if main_menu_photo:
        await callback.message.answer_photo(
            photo=main_menu_photo,
            caption=text,
            reply_markup=keyboard,
        )
    else:
        await callback.message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "admin:section:store")
async def open_store_admin(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    context: AppContext,
) -> None:
    if not _is_admin(callback.from_user.id, context):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    if isinstance(callback.message, Message):
        await open_store_admin_panel(callback.message, session)


@router.callback_query(F.data == "admin:gateway")
async def open_gateway_admin(callback: CallbackQuery, context: AppContext) -> None:
    if not _is_admin(callback.from_user.id, context):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    values = await store_settings(context)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "<b>Начальный экран</b>\n\n"
            f"Текст: {escape(values['gateway_message'])}\n"
            f"Первая кнопка: {escape(values['gateway_store_button'])}\n"
            f"Вторая кнопка: {escape(values['gateway_ai_button'])}",
            reply_markup=gateway_admin_menu(values),
        )


@router.callback_query(F.data.startswith("admin:gateway:edit:"))
async def begin_gateway_edit(
    callback: CallbackQuery,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not _is_admin(callback.from_user.id, context):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    key = (callback.data or "").rsplit(":", 1)[-1]
    if key not in GATEWAY_SETTINGS:
        await callback.answer("Настройка не найдена.", show_alert=True)
        return
    await state.set_state(GatewayAdminFlow.awaiting_value)
    await state.update_data(gateway_setting_key=key)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"Введите новое значение для «{GATEWAY_SETTINGS[key][0]}» одним сообщением."
        )


@router.message(GatewayAdminFlow.awaiting_value, F.text)
async def save_gateway_value(
    message: Message,
    state: FSMContext,
    context: AppContext,
) -> None:
    if not message.from_user or not _is_admin(message.from_user.id, context):
        await state.clear()
        return
    data = await state.get_data()
    key = str(data.get("gateway_setting_key") or "")
    value = (message.text or "").strip()
    if key not in GATEWAY_SETTINGS or not value:
        await message.answer("Значение не сохранено.")
        return
    async with context.db.sessions() as session:
        item = await session.get(BotSetting, key)
        if item:
            item.value = value
        else:
            session.add(BotSetting(key=key, title=GATEWAY_SETTINGS[key][0], value=value))
        await session.commit()
    await state.clear()
    values = await store_settings(context)
    await message.answer(
        "Сохранено ✅",
        reply_markup=gateway_admin_menu(values),
    )
