from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.keyboards import back_kb, main_menu_kb

router = Router()


@router.callback_query(F.data.in_({"buy", "pay_card", "pay_qr"}))
async def legacy_payment_start(callback: CallbackQuery) -> None:
    """Redirect old payment callbacks to the current sticker purchase flow."""
    await callback.message.answer(
        "Оплата теперь проходит через выбор акции и QR-кода.\n\n"
        "Нажмите кнопку участия, выберите количество стикеров и отправьте чек менеджеру.",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("paid:"))
async def legacy_paid_click(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "Чек по этой акции нужно отправить менеджеру, указанному в инструкции после выбора QR-кода.",
        reply_markup=back_kb("buy_sticker"),
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(
        "Оплата отменена. Можно вернуться к участию в акции.",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()
