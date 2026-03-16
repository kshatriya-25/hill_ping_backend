# HillPing — Razorpay Payment Service
#
# Payment flow:
# 1. Create Razorpay order (amount authorized, not captured)
# 2. Guest completes payment on frontend via Razorpay checkout
# 3. On owner accept → capture payment
# 4. On owner reject/timeout → refund payment

import hashlib
import hmac
import logging
from decimal import Decimal

import razorpay

from ..core.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> razorpay.Client:
    """Lazy-init Razorpay client."""
    global _client
    if _client is None:
        _client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    return _client


def create_razorpay_order(amount_inr: Decimal, booking_ref: str) -> dict:
    """
    Create a Razorpay order for payment authorization.
    Amount is in INR (converted to paise internally).

    Returns dict with: id, amount, currency, receipt, status
    """
    client = _get_client()
    amount_paise = int(amount_inr * 100)

    order_data = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": booking_ref,
        "payment_capture": 0,  # Manual capture (authorize only)
    }

    order = client.order.create(data=order_data)
    logger.info("Razorpay order created: %s for %s (₹%s)", order["id"], booking_ref, amount_inr)
    return order


def capture_payment(payment_id: str, amount_inr: Decimal) -> dict:
    """
    Capture an authorized payment (on owner accept).
    Amount must match the authorized amount.
    """
    client = _get_client()
    amount_paise = int(amount_inr * 100)

    result = client.payment.capture(payment_id, amount_paise, {"currency": "INR"})
    logger.info("Payment captured: %s (₹%s)", payment_id, amount_inr)
    return result


def refund_payment(payment_id: str, amount_inr: Decimal | None = None) -> dict:
    """
    Refund a payment (on owner reject/timeout or guest cancellation).
    If amount is None, full refund is issued.
    """
    client = _get_client()
    refund_data = {}
    if amount_inr is not None:
        refund_data["amount"] = int(amount_inr * 100)

    result = client.payment.refund(payment_id, refund_data)
    logger.info("Payment refunded: %s (amount: %s)", payment_id, amount_inr or "full")
    return result


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """
    Verify Razorpay payment signature using HMAC SHA256.
    This confirms the payment was not tampered with.
    """
    message = f"{order_id}|{payment_id}"
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """Verify Razorpay webhook signature."""
    try:
        client = _get_client()
        client.utility.verify_webhook_signature(
            body.decode(), signature, settings.RAZORPAY_KEY_SECRET
        )
        return True
    except Exception:
        return False
