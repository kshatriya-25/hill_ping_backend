# HillPing — Guest Access Code Service (V2)

import datetime
import hashlib
import logging
import secrets
import string
from datetime import timedelta, timezone

from sqlalchemy.orm import Session

from ..core.config import settings
from ..modals.masters import User
from ..modals.guest_access import GuestAccessCode, VisitCard
from ..utils.utils import password_context

logger = logging.getLogger(__name__)

MAX_CODE_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


class GuestAccessError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code


def _generate_code(length: int = 6) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(length))


def _generate_card_ref() -> str:
    chars = string.ascii_uppercase + string.digits
    return "V-" + "".join(secrets.choice(chars) for _ in range(6))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_access_code(
    phone: str,
    guest_name: str,
    mediator_id: int,
    db: Session,
) -> tuple[User, str, str]:
    """
    Generate a 6-digit access code for a guest.
    Creates guest User if not exists.
    Returns (user, raw_code, auto_login_token).
    """
    # Find or create guest user
    user = db.query(User).filter(User.phone == phone, User.role == "guest").first()
    if not user:
        # Auto-create guest account
        username = f"guest_{phone.replace('+', '').replace(' ', '')}"
        # Ensure unique username
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            username = f"{username}_{secrets.token_hex(3)}"

        user = User(
            name=guest_name,
            username=username,
            email=f"{username}@hillping.guest",  # placeholder
            phone=phone,
            password_hash="",  # no password yet, uses access code
            role="guest",
            is_active=True,
            acquired_by_mediator_id=mediator_id,
        )
        db.add(user)
        db.flush()
        logger.info("Auto-created guest user %d for phone %s", user.id, phone)

    # Check for existing active code for this phone
    existing_code = db.query(GuestAccessCode).filter(
        GuestAccessCode.phone == phone,
        GuestAccessCode.is_active == True,
        GuestAccessCode.expires_at > datetime.datetime.now(timezone.utc),
    ).first()

    if existing_code:
        # Deactivate old code
        existing_code.is_active = False

    # Generate new code
    raw_code = _generate_code()
    code_hash = password_context.hash(raw_code)

    # Generate auto-login token
    auto_login_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(auto_login_token)

    expires_at = datetime.datetime.now(timezone.utc) + timedelta(
        hours=settings.GUEST_ACCESS_CODE_VALIDITY_HOURS
    )

    access_code = GuestAccessCode(
        user_id=user.id,
        phone=phone,
        code_hash=code_hash,
        auth_token_hash=token_hash,
        is_active=True,
        created_by_mediator_id=mediator_id,
        expires_at=expires_at,
    )
    db.add(access_code)
    db.commit()
    db.refresh(user)

    logger.info("Access code generated for phone %s by mediator %d", phone, mediator_id)
    return user, raw_code, auto_login_token


def verify_access_code(phone: str, code: str, db: Session) -> User:
    """Verify a 6-digit access code. Rate-limited (5 attempts → 15-min lockout)."""
    access = db.query(GuestAccessCode).filter(
        GuestAccessCode.phone == phone,
        GuestAccessCode.is_active == True,
        GuestAccessCode.expires_at > datetime.datetime.now(timezone.utc),
    ).first()

    if not access:
        raise GuestAccessError("No active access code for this phone number", 401)

    # Check lockout
    if access.locked_until and access.locked_until > datetime.datetime.now(timezone.utc):
        raise GuestAccessError("Too many attempts. Try again later.", 429)

    # Verify code
    if not password_context.verify(code, access.code_hash):
        access.failed_attempts += 1
        if access.failed_attempts >= MAX_CODE_ATTEMPTS:
            access.locked_until = datetime.datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
        db.commit()
        raise GuestAccessError("Invalid access code", 401)

    # Reset attempts on success
    access.failed_attempts = 0
    access.locked_until = None
    db.commit()

    user = db.query(User).filter(User.id == access.user_id).first()
    if not user:
        raise GuestAccessError("User not found", 404)

    return user


def auto_login(token: str, db: Session) -> User:
    """Auto-login via URL token (Visit Card link click)."""
    token_hash = _hash_token(token)

    access = db.query(GuestAccessCode).filter(
        GuestAccessCode.auth_token_hash == token_hash,
        GuestAccessCode.is_active == True,
        GuestAccessCode.expires_at > datetime.datetime.now(timezone.utc),
    ).first()

    if not access:
        raise GuestAccessError("Invalid or expired login link", 401)

    user = db.query(User).filter(User.id == access.user_id).first()
    if not user:
        raise GuestAccessError("User not found", 404)

    return user


def create_visit_card(
    mediator_id: int,
    guest_phone: str,
    guest_name: str,
    guest_count: int,
    db: Session,
) -> tuple[VisitCard, str, str]:
    """
    Create a Visit Card for a tourist.
    Also generates access code and auto-login token.
    Returns (visit_card, raw_code, auto_login_token).
    """
    user, raw_code, auto_login_token = generate_access_code(
        phone=guest_phone,
        guest_name=guest_name,
        mediator_id=mediator_id,
        db=db,
    )

    card_ref = _generate_card_ref()
    while db.query(VisitCard).filter(VisitCard.card_ref == card_ref).first():
        card_ref = _generate_card_ref()

    expires_at = datetime.datetime.now(timezone.utc) + timedelta(
        hours=settings.GUEST_ACCESS_CODE_VALIDITY_HOURS
    )

    card = VisitCard(
        card_ref=card_ref,
        mediator_id=mediator_id,
        guest_id=user.id,
        guest_phone=guest_phone,
        guest_name=guest_name,
        guest_count=guest_count,
        status="active",
        sms_sent_at=datetime.datetime.now(timezone.utc),
        expires_at=expires_at,
    )
    db.add(card)
    db.commit()
    db.refresh(card)

    logger.info("Visit card %s created for guest %s by mediator %d", card_ref, guest_phone, mediator_id)
    return card, raw_code, auto_login_token
