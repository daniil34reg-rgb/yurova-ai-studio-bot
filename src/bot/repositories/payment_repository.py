from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models import Payment, PaymentStatus


class PaymentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: int, amount: int, payment_method: str = "card") -> Payment:
        payment = Payment(user_id=user_id, amount=amount, payment_method=payment_method)
        self.session.add(payment)
        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    async def get_by_id(self, payment_id: int) -> Payment | None:
        result = await self.session.execute(
            select(Payment)
            .options(selectinload(Payment.user))
            .where(Payment.id == payment_id)
        )
        return result.scalar_one_or_none()

    async def get_pending(self) -> list[Payment]:
        result = await self.session.execute(
            select(Payment)
            .options(selectinload(Payment.user))
            .where(Payment.status == PaymentStatus.pending)
            .order_by(Payment.created_at.asc())
        )
        return list(result.scalars().all())

    async def update_status(
        self, payment_id: int, status: PaymentStatus, comment: str | None = None
    ) -> Payment | None:
        payment = await self.get_by_id(payment_id)
        if payment:
            payment.status = status
            if comment:
                payment.admin_comment = comment
            await self.session.commit()
            await self.session.refresh(payment)
        return payment

    async def set_screenshot(self, payment_id: int, file_id: str) -> None:
        payment = await self.get_by_id(payment_id)
        if payment:
            payment.screenshot_file_id = file_id
            await self.session.commit()

    async def count_by_status(self, status: PaymentStatus) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Payment).where(Payment.status == status)
        )
        return result.scalar_one()

    async def sum_confirmed(self) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.status == PaymentStatus.confirmed)
        )
        return result.scalar_one()
