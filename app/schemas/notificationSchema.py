# HillPing — Notification preference schemas

from typing import Optional
from pydantic import BaseModel


class NotificationPreferenceUpdate(BaseModel):
    booking_updates: Optional[bool] = None
    ping_alerts: Optional[bool] = None
    review_alerts: Optional[bool] = None
    promotional: Optional[bool] = None
    email_notifications: Optional[bool] = None
    push_notifications: Optional[bool] = None


class NotificationPreferenceResponse(BaseModel):
    booking_updates: bool = True
    ping_alerts: bool = True
    review_alerts: bool = True
    promotional: bool = False
    email_notifications: bool = True
    push_notifications: bool = True

    model_config = {"from_attributes": True}
