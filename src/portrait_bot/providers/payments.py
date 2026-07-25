from __future__ import annotations

import base64
import hashlib
import hmac
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

import httpx

from portrait_bot.config import Settings


class PaymentProviderError(RuntimeError):
    pass


@dataclass(slots=True)
class Checkout:
    provider_order_id: str
    url: str


class PaymentProvider(ABC):
    @abstractmethod
    async def create_checkout(
        self,
        *,
        payment_id: str,
        telegram_id: int,
        title: str,
        amount: Decimal,
        credits: int,
    ) -> Checkout:
        raise NotImplementedError


class MockPaymentProvider(PaymentProvider):
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.base_url.rstrip("/")

    async def create_checkout(
        self,
        *,
        payment_id: str,
        telegram_id: int,
        title: str,
        amount: Decimal,
        credits: int,
    ) -> Checkout:
        del telegram_id, title, amount, credits
        return Checkout(
            provider_order_id=f"mock-{payment_id}",
            url=f"{self.base_url}/mock/pay/{payment_id}",
        )


class CloudPaymentsProvider(PaymentProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.cloudpayments_public_id or not settings.cloudpayments_api_secret:
            raise ValueError("CloudPayments credentials are missing")
        self.public_id = settings.cloudpayments_public_id
        self.api_secret = settings.cloudpayments_api_secret
        self.api_url = settings.cloudpayments_api_url.rstrip("/")
        self.offer_url = settings.cloudpayments_offer_url
        self.success_url = settings.cloudpayments_success_url or (
            settings.base_url.rstrip("/") + "/payments/success"
        )
        self.fail_url = settings.cloudpayments_fail_url or (
            settings.base_url.rstrip("/") + "/payments/fail"
        )
        self.cloudkassir_enabled = settings.cloudkassir_enabled
        self.receipt = {
            "taxationSystem": settings.cloudkassir_taxation_system,
            "items": [
                {
                    "label": title_placeholder(),
                    "price": 0,
                    "quantity": 1,
                    "amount": 0,
                    "vat": settings.cloudkassir_vat,
                    "method": settings.cloudkassir_receipt_method,
                    "object": settings.cloudkassir_receipt_object,
                    "measurementUnit": "шт",
                }
            ],
        }

    async def create_checkout(
        self,
        *,
        payment_id: str,
        telegram_id: int,
        title: str,
        amount: Decimal,
        credits: int,
    ) -> Checkout:
        payload: dict[str, object] = {
            "Amount": float(amount),
            "Currency": "RUB",
            "Description": title if credits <= 0 else f"{title}: {credits} генераций",
            "RequireConfirmation": False,
            "SendEmail": False,
            "InvoiceId": payment_id,
            "AccountId": str(telegram_id),
            "CultureName": "ru-RU",
            "SuccessRedirectUrl": self.success_url,
            "FailRedirectUrl": self.fail_url,
        }
        if self.offer_url:
            payload["OfferUri"] = self.offer_url
        if self.cloudkassir_enabled:
            receipt = json.loads(json.dumps(self.receipt))
            item = receipt["items"][0]
            item["label"] = title
            item["price"] = float(amount)
            item["amount"] = float(amount)
            payload["JsonData"] = {"cloudpayments": {"customerReceipt": receipt}}

        async with httpx.AsyncClient(
            auth=(self.public_id, self.api_secret),
            timeout=20,
        ) as client:
            response = await client.post(
                f"{self.api_url}/orders/create",
                json=payload,
                headers={"X-Request-ID": f"checkout-{payment_id}"},
            )
        response.raise_for_status()
        data = response.json()
        if not data.get("Success") or not data.get("Model", {}).get("Url"):
            raise PaymentProviderError(str(data.get("Message") or "CloudPayments error"))
        model = data["Model"]
        return Checkout(provider_order_id=str(model["Id"]), url=str(model["Url"]))


def title_placeholder() -> str:
    return "Пакет генераций"


def verify_cloudpayments_hmac(body: bytes, signature: str | None, secret: str) -> bool:
    if not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature)


def build_payment_provider(settings: Settings) -> PaymentProvider:
    if settings.payment_provider == "cloudpayments":
        return CloudPaymentsProvider(settings)
    return MockPaymentProvider(settings)
