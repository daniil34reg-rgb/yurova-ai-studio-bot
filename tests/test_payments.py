import base64
import hashlib
import hmac

from portrait_bot.providers.payments import verify_cloudpayments_hmac


def test_cloudpayments_hmac() -> None:
    body = b"InvoiceId=abc&Amount=490.00"
    secret = "secret"
    signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    assert verify_cloudpayments_hmac(body, signature, secret)
    assert not verify_cloudpayments_hmac(body + b"x", signature, secret)
    assert not verify_cloudpayments_hmac(body, None, secret)
