from aiogram import Bot

from bot.config import settings
from bot.models import Payment
from bot.keyboards import admin_payment_kb
from bot.logging_setup.logger import logger


class AdminService:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def notify_new_payment(self, payment: Payment) -> None:
        user = payment.user
        text = (
            f"💰 <b>Новая оплата #{payment.id}</b>\n\n"
            f"👤 Пользователь: {user.full_name}"
            + (f" (@{user.username})" if user.username else "")
            + f"\n"
            f"🆔 TG ID: <code>{user.telegram_id}</code>\n"
            f"💵 Сумма: <b>{payment.amount} ₽</b>\n"
            f"💳 Метод: {payment.payment_method}\n"
        )

        for admin_id in settings.admin_id_list:
            try:
                # Send screenshot if available
                if payment.screenshot_file_id:
                    await self.bot.send_photo(
                        chat_id=admin_id,
                        photo=payment.screenshot_file_id,
                        caption=text,
                        reply_markup=admin_payment_kb(payment.id),
                        parse_mode="HTML",
                    )
                else:
                    await self.bot.send_message(
                        chat_id=admin_id,
                        text=text,
                        reply_markup=admin_payment_kb(payment.id),
                        parse_mode="HTML",
                    )
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")

    async def notify_error(self, error: str) -> None:
        for admin_id in settings.admin_id_list:
            try:
                await self.bot.send_message(
                    chat_id=admin_id,
                    text=f"🚨 <b>Ошибка бота</b>\n\n<code>{error}</code>",
                    parse_mode="HTML",
                )
            except Exception:
                pass

    async def get_stats_text(
        self,
        total_users: int,
        pending_payments: int,
        confirmed_payments: int,
        rejected_payments: int,
        total_revenue: int,
    ) -> str:
        return (
            f"📊 <b>Статистика</b>\n\n"
            f"👥 Пользователей: <b>{total_users}</b>\n\n"
            f"💰 Оплаты:\n"
            f"  ⏳ Ожидают: <b>{pending_payments}</b>\n"
            f"  ✅ Подтверждены: <b>{confirmed_payments}</b>\n"
            f"  ❌ Отклонены: <b>{rejected_payments}</b>\n\n"
            f"💵 Выручка: <b>{total_revenue} ₽</b>"
        )
