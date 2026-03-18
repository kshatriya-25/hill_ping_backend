# HillPing — Guest Access Code endpoints (V2)

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address

from ...core.config import settings
from ...database.session import getdb
from ...modals.masters import User
from ...services.guest_access import (
    verify_access_code, auto_login, GuestAccessError,
)
from ...utils.utils import (
    create_access_token, create_refresh_token,
    get_current_user, get_hashed_password, validate_password_strength,
)

router = APIRouter(tags=["guest-access"])
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)


class CodeLoginRequest(BaseModel):
    phone: str = Field(..., max_length=15)
    code: str = Field(..., min_length=6, max_length=6)


class SetPasswordRequest(BaseModel):
    password: str = Field(..., min_length=8)


@router.post("/login")
@limiter.limit(settings.RATE_LIMIT_LOGIN)
def login_with_code(
    request: Request,
    data: CodeLoginRequest,
    db: Session = Depends(getdb),
):
    """Login with phone number + 6-digit access code."""
    try:
        user = verify_access_code(data.phone, data.code, db)
    except GuestAccessError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    access_token = create_access_token(user.id, user.username, user.role)
    refresh_token = create_refresh_token(user.id, user.username, user.role, db=db)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "name": user.name,
            "phone": user.phone,
            "role": user.role,
        },
    }


@router.get("/auto-login/{token}")
def auto_login_endpoint(
    token: str,
    db: Session = Depends(getdb),
):
    """Auto-login via Visit Card URL token."""
    try:
        user = auto_login(token, db)
    except GuestAccessError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    access_token = create_access_token(user.id, user.username, user.role)
    refresh_token = create_refresh_token(user.id, user.username, user.role, db=db)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "name": user.name,
            "phone": user.phone,
            "role": user.role,
        },
    }


@router.post("/set-password")
def set_password(
    data: SetPasswordRequest,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Authenticated guest sets a permanent password for future logins."""
    validate_password_strength(data.password)

    current_user.password_hash = get_hashed_password(data.password)
    db.commit()

    return {"detail": "Password set successfully. You can now log in with username and password."}
