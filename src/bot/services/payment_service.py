from bot.models import Payment, PaymentStatus
from bot.repositories import PaymentRepository
from bot.config import settings


class PaymentService:
    def __init__(self, repo: PaymentRepository):
        self.repo = repo

    async def create_payment(self, user_id: int, method: str = "card") -> Payment:
        return await self.repo.create(
            user_id=user_id,
            amount=settings.payment_amount,
            payment_method=method,
        )

    async def attach_screenshot(self, payment_id: int, file_id: str) -> None:
        await self.repo.set_screenshot(payment_id, file_id)

    async def confirm(self, payment_id: int) -> Payment | None:
        return await self.repo.update_status(payment_id, PaymentStatus.confirmed)

    async def reject(self, payment_id: int, reason: str) -> Payment | None:
        return await self.repo.update_status(payment_id, PaymentStatus.rejected, reason)

    async def get_pending(self) -> list[Payment]:
        return await self.repo.get_pending()

    async def get_payment(self, payment_id: int) -> Payment | None:
        return await self.repo.get_by_id(payment_id)

    def build_card_instructions(self) -> str:
        return (
            f"💳 <b>Payment Instructions</b>\n\n"
            f"Transfer <b>{settings.payment_amount} ₽</b> to:\n\n"
            f"🏦 Bank: <b>{settings.payment_bank}</b>\n"
            f"💳 Card: <code>{settings.payment_card}</code>\n"
            f"👤 Recipient: <b>{settings.payment_recipient}</b>\n\n"
            f"After payment, press <b>I've Paid</b> and send a screenshot."
        )

    def build_qr_data(self) -> str:
        return (
            f"ST00012|Name={settings.payment_recipient}"
            f"|PersonalAcc={settings.payment_card.replace(' ', '')}"
            f"|Sum={settings.payment_amount * 100}"
        )
