# HillPing — FCM Push Notification Service

import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..core.config import settings
from ..modals.masters import User

logger = logging.getLogger(__name__)

_firebase_initialized = False


def _init_firebase():
    """Lazy-init Firebase Admin SDK."""
    global _firebase_initialized
    if _firebase_initialized:
        return

    if not settings.FCM_CREDENTIALS_PATH:
        logger.warning("FCM_CREDENTIALS_PATH not set — push notifications disabled")
        return

    try:
        import firebase_admin
        from firebase_admin import credentials

        cred = credentials.Certificate(settings.FCM_CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        logger.info("Firebase Admin SDK initialized")
    except Exception as e:
        logger.error("Failed to initialize Firebase: %s", e)


def send_push_to_user(
    user_id: int,
    title: str,
    body: str,
    data: Optional[dict] = None,
    db: Optional[Session] = None,
) -> bool:
    """
    Send a push notification to a user via FCM.
    Returns True if sent successfully.
    """
    _init_firebase()

    if not _firebase_initialized:
        logger.debug("Firebase not initialized, skipping push to user %d", user_id)
        return False

    if db is None:
        return False

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.fcm_token:
        logger.debug("No FCM token for user %d", user_id)
        return False

    try:
        from firebase_admin import messaging

        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data=data or {},
            token=user.fcm_token,
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    sound="default",
                    channel_id="hillping_bookings",
                ),
            ),
        )
        response = messaging.send(message)
        logger.info("FCM sent to user %d: %s", user_id, response)
        return True

    except Exception as e:
        logger.error("FCM send failed for user %d: %s", user_id, e)
        # Clear invalid token
        if "UNREGISTERED" in str(e) or "INVALID_ARGUMENT" in str(e):
            user.fcm_token = None
            db.commit()
        return False


def send_ping_notification(owner_id: int, ping_data: dict, db: Session) -> bool:
    """Send a ping notification to the property owner."""
    property_name = ping_data.get("property_name", "your property")
    check_in = ping_data.get("check_in", "")
    guests = ping_data.get("guests_count", 1)

    return send_push_to_user(
        user_id=owner_id,
        title="New Booking Request!",
        body=f"{guests} guest(s) want to book {property_name} from {check_in}. Respond in 30 seconds!",
        data={
            "type": "ping_received",
            "session_id": str(ping_data.get("session_id", "")),
            "property_id": str(ping_data.get("property_id", "")),
        },
        db=db,
    )


def send_booking_confirmation(guest_id: int, booking_ref: str, property_name: str, db: Session) -> bool:
    """Send booking confirmation notification to guest."""
    return send_push_to_user(
        user_id=guest_id,
        title="Booking Confirmed!",
        body=f"Your booking {booking_ref} at {property_name} is confirmed.",
        data={"type": "booking_confirmed", "booking_ref": booking_ref},
        db=db,
    )


def send_cancellation_notification(user_id: int, booking_ref: str, db: Session) -> bool:
    """Send cancellation notification."""
    return send_push_to_user(
        user_id=user_id,
        title="Booking Cancelled",
        body=f"Booking {booking_ref} has been cancelled. Refund will be processed shortly.",
        data={"type": "booking_cancelled", "booking_ref": booking_ref},
        db=db,
    )
