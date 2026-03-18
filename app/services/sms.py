# HillPing — SMS Service (V2)
#
# Supports MSG91 and Twilio. Provider configured via SMS_PROVIDER env var.

import logging
from ..core.config import settings

logger = logging.getLogger(__name__)


def send_sms(phone: str, message: str) -> bool:
    """Send an SMS via configured provider. Returns True on success."""
    provider = settings.SMS_PROVIDER.lower()

    if provider == "msg91":
        return _send_msg91(phone, message)
    elif provider == "twilio":
        return _send_twilio(phone, message)
    else:
        logger.warning("SMS_PROVIDER not configured. SMS to %s: %s", phone, message)
        return False


def send_visit_card_sms(phone: str, guest_name: str, card_url: str, access_code: str, mediator_name: str) -> bool:
    """Send the Visit Card SMS to a tourist."""
    message = (
        f"Hi {guest_name}! Welcome to HillPing.\n\n"
        f"Your access code: {access_code}\n\n"
        f"Your agent {mediator_name} is finding rooms for you.\n"
        f"Open your Visit Card: {card_url}\n\n"
        f"Or log in at hillping.in with your phone + code.\n"
        f"Price protection. Room Match Guarantee. Full refund guarantee."
    )
    return send_sms(phone, message)


def send_trip_card_sms(phone: str, guest_name: str, trip_url: str, property_name: str) -> bool:
    """Send the Trip Card SMS after booking."""
    message = (
        f"Hi {guest_name}! Your booking at {property_name} is confirmed.\n\n"
        f"Trip Card: {trip_url}\n\n"
        f"Directions, owner contact, and check-in details are all in your Trip Card."
    )
    return send_sms(phone, message)


def send_access_code_sms(phone: str, code: str) -> bool:
    """Send just the access code."""
    message = f"Your HillPing access code: {code}. Valid for 24 hours."
    return send_sms(phone, message)


# ── Provider implementations ──────────────────────────────────────────────────

def _send_msg91(phone: str, message: str) -> bool:
    """Send via MSG91 API."""
    try:
        import requests
        url = "https://api.msg91.com/api/v5/flow/"
        headers = {"authkey": settings.MSG91_AUTH_KEY}
        payload = {
            "sender": settings.MSG91_SENDER_ID,
            "route": "4",
            "country": "91",
            "sms": [{"message": message, "to": [phone]}],
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code == 200:
            logger.info("SMS sent via MSG91 to %s", phone)
            return True
        logger.error("MSG91 error: %s %s", resp.status_code, resp.text)
        return False
    except Exception as e:
        logger.error("MSG91 exception: %s", e)
        return False


def _send_twilio(phone: str, message: str) -> bool:
    """Send via Twilio API."""
    try:
        from twilio.rest import Client
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        msg = client.messages.create(
            body=message,
            from_=settings.TWILIO_FROM_NUMBER,
            to=phone,
        )
        logger.info("SMS sent via Twilio to %s (sid=%s)", phone, msg.sid)
        return True
    except Exception as e:
        logger.error("Twilio exception: %s", e)
        return False
