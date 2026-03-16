# backend/app/api/auth/endpoints.py

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from ...core.config import settings
from ...database.session import getdb
from ...modals.masters import User
from ...schemas.masterSchema import UserCreate
from ...utils.utils import (
    verify_password,
    get_hashed_password,
    create_access_token,
    create_refresh_token,
    rotate_refresh_token,
    revoke_refresh_token,
    revoke_all_user_refresh_tokens,
    is_account_locked,
    record_failed_login,
    reset_login_attempts,
    get_current_user,
)

router = APIRouter(tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


# ── Register ──────────────────────────────────────────────────────────────────

@router.post("/register")
@limiter.limit(settings.RATE_LIMIT_LOGIN)
def register(
    request: Request,
    user_data: UserCreate,
    db: Session = Depends(getdb),
):
    """
    Self-registration for guests and owners.
    Admins can only be created via the bootstrap endpoint.
    """
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    new_user = User(
        name=user_data.name,
        username=user_data.username,
        email=user_data.email,
        phone=user_data.phone,
        password_hash=get_hashed_password(user_data.password),
        role=user_data.role,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    access_token = create_access_token(new_user.id, new_user.username, new_user.role)
    refresh_token = create_refresh_token(new_user.id, new_user.username, new_user.role, db=db)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": new_user.id,
            "username": new_user.username,
            "email": new_user.email,
            "name": new_user.name,
            "role": new_user.role,
        },
    }


# ── Login ──────────────────────────────────────────────────────────────────────

@router.post("/login")
@limiter.limit(settings.RATE_LIMIT_LOGIN)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(getdb),
):
    """
    Authenticate with username + password.
    Returns a short-lived access token and a long-lived refresh token.
    Enforces per-IP rate limiting and account lockout on repeated failures.
    """
    user: User | None = db.query(User).filter(User.username == form_data.username).first()

    # Deliberately return the same error for missing user and wrong password
    # to avoid username enumeration.
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    if is_account_locked(user):
        raise HTTPException(
            status_code=429,
            detail=f"Account locked due to too many failed attempts. Try again in {settings.LOCKOUT_MINUTES} minutes.",
        )

    if not verify_password(form_data.password, user.password_hash):
        record_failed_login(user, db)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Successful login
    reset_login_attempts(user, db)

    access_token = create_access_token(user.id, user.username, user.role)
    refresh_token = create_refresh_token(user.id, user.username, user.role, db=db)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


# ── Refresh ────────────────────────────────────────────────────────────────────

@router.post("/refresh")
@limiter.limit(settings.RATE_LIMIT_REFRESH)
def refresh(
    request: Request,
    body: RefreshRequest,
    db: Session = Depends(getdb),
):
    """
    Rotate a refresh token.
    The old token is immediately revoked and a new pair is returned.
    Reuse of a previously revoked token revokes ALL sessions for that user.
    """
    new_refresh_token = rotate_refresh_token(body.refresh_token, db)

    # Decode the *new* token to get user info for the new access token
    from jose import jwt as _jwt
    payload = _jwt.decode(new_refresh_token, settings.JWT_REFRESH_SECRET_KEY, algorithms=[settings.ALGORITHM])

    new_access_token = create_access_token(
        payload["user_id"], payload["username"], payload["role"]
    )

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }


# ── Logout ─────────────────────────────────────────────────────────────────────

@router.post("/logout")
def logout(
    body: LogoutRequest,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Revoke the supplied refresh token (single-device logout)."""
    revoke_refresh_token(body.refresh_token, db)
    return {"detail": "Logged out successfully"}


@router.post("/logout-all")
def logout_all(
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Revoke ALL refresh tokens for the current user (all-device logout)."""
    revoke_all_user_refresh_tokens(current_user.id, db)
    return {"detail": "All sessions revoked"}


# ── Authenticated check ────────────────────────────────────────────────────────

@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "name": current_user.name,
        "role": current_user.role,
    }
