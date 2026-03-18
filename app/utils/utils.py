# OM VIGHNHARTAYE NAMO NAMAH:
# backend/app/utils/utils.py

import datetime
import hashlib
import re
from datetime import timedelta, timezone
from typing import Optional

from jose import jwt, JWTError
from fastapi import HTTPException, Depends, Request
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from ..core.config import settings
from ..database.session import getdb
from ..modals.masters import User, RefreshToken

JWT_SECRET_KEY = settings.JWT_SECRET_KEY
JWT_REFRESH_SECRET_KEY = settings.JWT_REFRESH_SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_MINUTES = settings.REFRESH_TOKEN_EXPIRE_MINUTES

password_context = CryptContext(schemes=["argon2"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ── Response helper ────────────────────────────────────────────────────────────

def response_strct(status_code='', detail='', data={}, error=''):
    return {
        "status_code": status_code,
        "detail": detail,
        "data": data,
        "error": error,
    }


# ── Password helpers ───────────────────────────────────────────────────────────

def get_hashed_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(password: str, hashed_pass: str) -> bool:
    return password_context.verify(password, hashed_pass)


_PASSWORD_PATTERN = re.compile(
    r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]).{8,}$'
)


def validate_password_strength(password: str) -> None:
    """Raise HTTPException 422 if password does not meet complexity requirements."""
    if not _PASSWORD_PATTERN.match(password):
        raise HTTPException(
            status_code=422,
            detail=(
                "Password must be at least 8 characters and contain "
                "an uppercase letter, a lowercase letter, a digit, and a special character."
            ),
        )


# ── Token helpers ──────────────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    """SHA-256 hash of a raw token — stored in DB, never the raw value."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(
    user_id: int,
    username: str,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    expires_at = datetime.datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode = {
        "exp": expires_at,
        "iat": datetime.datetime.now(timezone.utc),
        "type": "access",
        "user_id": user_id,
        "username": username,
        "role": role,
    }
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(
    user_id: int,
    username: str,
    role: str,
    db: Optional[Session] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a refresh token and persist its hash in the DB."""
    expires_at = datetime.datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES)
    )
    to_encode = {
        "exp": expires_at,
        "iat": datetime.datetime.now(timezone.utc),
        "type": "refresh",
        "user_id": user_id,
        "username": username,
        "role": role,
    }
    raw_token = jwt.encode(to_encode, JWT_REFRESH_SECRET_KEY, algorithm=ALGORITHM)

    if db is not None:
        token_record = RefreshToken(
            user_id=user_id,
            token_hash=_hash_token(raw_token),
            expires_at=expires_at,
            revoked=False,
        )
        db.add(token_record)
        db.commit()

    return raw_token


def rotate_refresh_token(
    old_raw_token: str,
    db: Session,
) -> str:
    """
    Validate the incoming refresh token, revoke it, and issue a new one.
    Raises HTTPException on any failure (expired, revoked, unknown).
    """
    try:
        payload = jwt.decode(old_raw_token, JWT_REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    old_hash = _hash_token(old_raw_token)
    record = db.query(RefreshToken).filter(RefreshToken.token_hash == old_hash).first()

    if not record:
        raise HTTPException(status_code=401, detail="Refresh token not recognised")
    if record.revoked:
        # Token reuse detected — revoke ALL tokens for this user (compromise signal)
        db.query(RefreshToken).filter(RefreshToken.user_id == record.user_id).update({"revoked": True})
        db.commit()
        raise HTTPException(status_code=401, detail="Refresh token already used. All sessions revoked.")
    if record.expires_at.replace(tzinfo=timezone.utc) < datetime.datetime.now(timezone.utc):
        record.revoked = True
        db.commit()
        raise HTTPException(status_code=401, detail="Refresh token has expired")

    user_id: int = payload["user_id"]
    username: str = payload["username"]
    role: str = payload["role"]

    # Revoke the old token (rotation)
    record.revoked = True
    db.commit()

    # Issue a fresh token
    return create_refresh_token(user_id, username, role, db=db)


def revoke_refresh_token(raw_token: str, db: Session) -> None:
    """Revoke a single refresh token (logout)."""
    token_hash = _hash_token(raw_token)
    record = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if record and not record.revoked:
        record.revoked = True
        db.commit()


def revoke_all_user_refresh_tokens(user_id: int, db: Session) -> None:
    """Revoke every refresh token for a user (logout-all / password change)."""
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked == False,  # noqa: E712
    ).update({"revoked": True})
    db.commit()


# ── Account-lockout helpers ────────────────────────────────────────────────────

def is_account_locked(user: User) -> bool:
    if user.locked_until is None:
        return False
    return user.locked_until.replace(tzinfo=timezone.utc) > datetime.datetime.now(timezone.utc)


def record_failed_login(user: User, db: Session) -> None:
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
        user.locked_until = datetime.datetime.now(timezone.utc) + timedelta(
            minutes=settings.LOCKOUT_MINUTES
        )
    db.commit()


def reset_login_attempts(user: User, db: Session) -> None:
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.datetime.now(timezone.utc)
    db.commit()


# ── Auth dependency ────────────────────────────────────────────────────────────

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(getdb)) -> User:
    """Decode the access JWT and return the authenticated User object."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that additionally checks admin role."""
    if getattr(current_user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user


def require_owner(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that checks owner role."""
    if getattr(current_user, "role", None) != "owner":
        raise HTTPException(status_code=403, detail="Owner privileges required")
    return current_user


def require_guest(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that checks guest role."""
    if getattr(current_user, "role", None) != "guest":
        raise HTTPException(status_code=403, detail="Guest account required")
    return current_user


def require_mediator(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that checks mediator role."""
    if getattr(current_user, "role", None) != "mediator":
        raise HTTPException(status_code=403, detail="Mediator privileges required")
    return current_user


def require_role(*roles: str):
    """Factory: returns a dependency that accepts any of the given roles."""
    def _checker(current_user: User = Depends(get_current_user)) -> User:
        if getattr(current_user, "role", None) not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"One of these roles required: {', '.join(roles)}",
            )
        return current_user
    return _checker
