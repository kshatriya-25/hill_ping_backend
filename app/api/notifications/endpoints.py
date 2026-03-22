# HillPing — FCM Token management & Notification Preferences endpoints

from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database.session import getdb
from ...modals.masters import User, DeviceToken
from ...modals.notification_preference import NotificationPreference
from ...schemas.notificationSchema import NotificationPreferenceUpdate, NotificationPreferenceResponse
from ...utils.utils import get_current_user

router = APIRouter(tags=["notifications"])


class TokenRegister(BaseModel):
    fcm_token: str = Field(..., min_length=10, max_length=500)
    device_name: Optional[str] = Field(None, max_length=100)


@router.post("/register-token")
def register_fcm_token(
    data: TokenRegister,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Register an FCM token for push notifications. Supports multiple devices per user."""
    # Check if this token already exists (maybe from a different user or same user)
    existing = db.query(DeviceToken).filter(DeviceToken.fcm_token == data.fcm_token).first()
    if existing:
        # Token exists — reassign to current user if needed
        existing.user_id = current_user.id
        existing.device_name = data.device_name
    else:
        device = DeviceToken(
            user_id=current_user.id,
            fcm_token=data.fcm_token,
            device_name=data.device_name,
        )
        db.add(device)

    # Also keep legacy column in sync for backward compat
    current_user.fcm_token = data.fcm_token
    db.commit()
    return {"detail": "FCM token registered"}


class TokenUnregister(BaseModel):
    fcm_token: Optional[str] = Field(None, min_length=10, max_length=500)


@router.delete("/unregister-token")
def unregister_fcm_token(
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Remove all FCM tokens for the current user."""
    db.query(DeviceToken).filter(DeviceToken.user_id == current_user.id).delete()
    current_user.fcm_token = None
    db.commit()
    return {"detail": "FCM tokens removed"}


@router.post("/unregister-token")
def unregister_single_fcm_token(
    data: TokenUnregister,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Remove a specific FCM token for the current user."""
    if data.fcm_token:
        db.query(DeviceToken).filter(
            DeviceToken.user_id == current_user.id,
            DeviceToken.fcm_token == data.fcm_token,
        ).delete()
    else:
        db.query(DeviceToken).filter(DeviceToken.user_id == current_user.id).delete()
        current_user.fcm_token = None
    db.commit()
    return {"detail": "FCM token removed"}


@router.get("/preferences", response_model=NotificationPreferenceResponse)
def get_preferences(
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Get current user's notification preferences. Creates defaults if none exist."""
    pref = db.query(NotificationPreference).filter(
        NotificationPreference.user_id == current_user.id
    ).first()

    if not pref:
        pref = NotificationPreference(user_id=current_user.id)
        db.add(pref)
        db.commit()
        db.refresh(pref)

    return pref


@router.patch("/preferences", response_model=NotificationPreferenceResponse)
def update_preferences(
    data: NotificationPreferenceUpdate,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Update notification preferences for the current user."""
    pref = db.query(NotificationPreference).filter(
        NotificationPreference.user_id == current_user.id
    ).first()

    if not pref:
        pref = NotificationPreference(user_id=current_user.id)
        db.add(pref)
        db.flush()

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(pref, field, value)

    db.commit()
    db.refresh(pref)
    return pref
