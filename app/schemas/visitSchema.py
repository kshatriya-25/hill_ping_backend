# HillPing — Visit Request schemas (V2)

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class VisitRequestCreate(BaseModel):
    """Mediator requests a property visit (creates hold)."""
    property_id: int
    room_id: Optional[int] = None
    guest_id: Optional[int] = None
    guest_count: int = Field(default=1, ge=1, le=20)
    eta_minutes: Optional[int] = Field(default=None, ge=1, le=120)
    ping_session_id: Optional[int] = None


class VisitPassRequest(BaseModel):
    """Tourist rejected the property."""
    reason: Optional[str] = Field(
        default=None,
        max_length=500,
    )


class VisitRequestResponse(BaseModel):
    id: int
    visit_ref: str
    mediator_id: int
    property_id: int
    room_id: Optional[int] = None
    guest_id: Optional[int] = None
    owner_id: int
    guest_count: int
    eta_minutes: Optional[int] = None
    status: str
    hold_expires_at: Optional[datetime] = None
    hold_extended: bool = False
    hold_remaining_seconds: Optional[int] = None
    pass_reason: Optional[str] = None
    arrived_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    tour_session_id: Optional[int] = None
    tour_stop_order: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
