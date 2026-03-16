# HillPing — FCM Token management endpoints

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database.session import getdb
from ...modals.masters import User
from ...utils.utils import get_current_user

router = APIRouter(tags=["notifications"])


class TokenRegister(BaseModel):
    fcm_token: str = Field(..., min_length=10, max_length=500)


@router.post("/register-token")
def register_fcm_token(
    data: TokenRegister,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Register or update FCM token for push notifications."""
    current_user.fcm_token = data.fcm_token
    db.commit()
    return {"detail": "FCM token registered"}


@router.delete("/unregister-token")
def unregister_fcm_token(
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Remove FCM token (disable push notifications)."""
    current_user.fcm_token = None
    db.commit()
    return {"detail": "FCM token removed"}
