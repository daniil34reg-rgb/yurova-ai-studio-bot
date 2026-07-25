from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote_plus

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from portrait_bot.bot import setup_commands
from portrait_bot.catalog import seed_catalog
from portrait_bot.config import Settings, get_settings
from portrait_bot.models import Payment, PaymentStatus, User
from portrait_bot.money import format_rub
from portrait_bot.providers.payments import verify_cloudpayments_hmac
from portrait_bot.runtime import cancel_task, worker_loop
from portrait_bot.services import add_wallet_entry, mark_payment_paid


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    from portrait_bot.app_factory import create_context

    context = create_context(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await context.db.create_all()
        async with context.db.sessions() as session:
            await seed_catalog(
                session,
                context.settings.templates_file,
                context.settings.packages_file,
                context.settings.features_file,
            )
        task: asyncio.Task[object] | None = asyncio.create_task(worker_loop(context))
        if context.bot:
            await setup_commands(context.bot, context)
            if context.settings.telegram_mode == "webhook":
                await context.bot.set_webhook(
                    context.settings.base_url.rstrip("/") + "/telegram/webhook",
                    secret_token=context.settings.telegram_webhook_secret,
                    allowed_updates=context.dispatcher.resolve_used_update_types()
                    if context.dispatcher
                    else None,
                )
        app.state.context = context
        yield
        await cancel_task(task)
        if context.bot:
            await context.bot.session.close()
        await context.db.dispose()

    app = FastAPI(
        title="Portrait Commerce Bot",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.context = context

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "environment": context.settings.app_env,
            "telegram_configured": bool(context.bot),
            "image_provider": context.settings.image_provider,
            "payment_provider": context.settings.payment_provider,
        }

    @app.post("/telegram/webhook")
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, bool]:
        if not context.bot or not context.dispatcher:
            raise HTTPException(status_code=503, detail="Telegram is not configured")
        if x_telegram_bot_api_secret_token != context.settings.telegram_webhook_secret:
            raise HTTPException(status_code=403, detail="Invalid webhook secret")
        update = Update.model_validate(await request.json(), context={"bot": context.bot})
        await context.dispatcher.feed_update(context.bot, update, context=context)
        return {"ok": True}

    @app.post("/webhooks/cloudpayments/{event_type}")
    async def cloudpayments_webhook(
        event_type: str,
        request: Request,
        x_content_hmac: str | None = Header(default=None),
        content_hmac: str | None = Header(default=None),
    ) -> JSONResponse:
        secret = context.settings.cloudpayments_api_secret
        if not secret:
            raise HTTPException(status_code=503, detail="CloudPayments is not configured")
        body = await request.body()
        decoded_body = unquote_plus(body.decode("utf-8")).encode("utf-8")
        signature_valid = (
            bool(x_content_hmac) and verify_cloudpayments_hmac(decoded_body, x_content_hmac, secret)
        ) or (bool(content_hmac) and verify_cloudpayments_hmac(body, content_hmac, secret))
        if not signature_valid:
            raise HTTPException(status_code=403, detail="Invalid signature")
        form = await request.form()
        values = {str(key): str(value) for key, value in form.items()}
        payment_id = values.get("InvoiceId")
        if not payment_id:
            return JSONResponse({"code": 13})

        if event_type.lower() == "check":
            async with context.db.sessions() as session:
                payment = await session.get(Payment, payment_id)
                if not payment:
                    return JSONResponse({"code": 13})
                try:
                    amount = Decimal(values.get("Amount", ""))
                except InvalidOperation:
                    return JSONResponse({"code": 13})
                user = await session.get(User, payment.user_id)
                valid = (
                    Decimal(payment.amount) == amount
                    and values.get("Currency") == payment.currency
                    and user is not None
                    and values.get("AccountId") == str(user.telegram_id)
                    and payment.status in {PaymentStatus.CREATED.value, PaymentStatus.PENDING.value}
                )
            return JSONResponse({"code": 0 if valid else 13})

        if event_type.lower() == "pay":
            try:
                amount = Decimal(values["Amount"])
                transaction_id = values["TransactionId"]
                async with context.db.sessions() as session:
                    current = await session.get(Payment, payment_id)
                    if not current or values.get("Currency") != current.currency:
                        return JSONResponse({"code": 13})
                    payment, credited = await mark_payment_paid(
                        session,
                        payment_id=payment_id,
                        transaction_id=transaction_id,
                        amount=amount,
                        account_id=values.get("AccountId"),
                        credit_validity_days=context.settings.credit_validity_days,
                    )
                    user = await session.get(User, payment.user_id)
                if credited and user and context.bot:
                    await context.bot.send_message(
                        user.telegram_id,
                        "Оплата подтверждена ✅\n"
                        f"Баланс пополнен на {format_rub(payment.amount)}.",
                    )
                return JSONResponse({"code": 0})
            except (LookupError, ValueError, KeyError, InvalidOperation):
                return JSONResponse({"code": 13})

        if event_type.lower() == "fail":
            async with context.db.sessions() as session:
                payment = await session.get(Payment, payment_id)
                if payment and payment.status != PaymentStatus.PAID.value:
                    payment.status = PaymentStatus.FAILED.value
                    await session.commit()
            return JSONResponse({"code": 0})

        if event_type.lower() == "refund":
            async with context.db.sessions() as session:
                payment = await session.get(Payment, payment_id)
                if not payment:
                    return JSONResponse({"code": 13})
                payment.status = PaymentStatus.REFUNDED.value
                await session.commit()
                await add_wallet_entry(
                    session,
                    user_id=payment.user_id,
                    amount_rub=-Decimal(payment.amount),
                    entry_type="refund",
                    idempotency_key=f"payment:{payment.id}:wallet:refund",
                    reference_type="payment",
                    reference_id=payment.id,
                )
            return JSONResponse({"code": 0})

        return JSONResponse({"code": 0})

    @app.get("/mock/pay/{payment_id}", response_class=HTMLResponse)
    async def mock_pay(payment_id: str) -> str:
        if context.settings.payment_provider != "mock":
            raise HTTPException(status_code=404)
        async with context.db.sessions() as session:
            payment, _ = await mark_payment_paid(
                session,
                payment_id=payment_id,
                transaction_id=f"mock-transaction-{payment_id}",
                credit_validity_days=context.settings.credit_validity_days,
            )
        return (
            "<!doctype html><html><meta charset='utf-8'><body style='font-family:sans-serif;"
            "max-width:600px;margin:80px auto'><h1>Оплата подтверждена ✅</h1>"
            f"<p>Баланс пополнен на {format_rub(payment.amount)}.</p>"
            "<p>Вернитесь в Telegram.</p></body></html>"
        )

    @app.get("/payments/success", response_class=HTMLResponse)
    async def payment_success() -> str:
        return "<h1>Оплата принята</h1><p>Вернитесь в Telegram.</p>"

    @app.get("/payments/fail", response_class=HTMLResponse)
    async def payment_fail() -> str:
        return "<h1>Оплата не завершена</h1><p>Попробуйте ещё раз в Telegram.</p>"

    return app


app = create_app()
