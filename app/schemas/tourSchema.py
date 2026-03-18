# HillPing — Tour Session schemas (V2)

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class TourStartRequest(BaseModel):
    """Start a multi-property tour."""
    property_ids: list[int] = Field(..., min_length=1, max_length=3)
    guest_id: Optional[int] = None
    guest_count: int = Field(default=1, ge=1, le=20)
    eta_minutes: Optional[int] = Field(default=None, ge=1, le=120)


class TourNextStopRequest(BaseModel):
    """Pass on current stop."""
    reason: Optional[str] = Field(default=None, max_length=500)


class TourStopResponse(BaseModel):
    id: int
    stop_index: int
    property_id: int
    status: str
    visit_request_id: Optional[int] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TourSessionResponse(BaseModel):
    id: int
    tour_ref: str
    mediator_id: int
    guest_id: Optional[int] = None
    status: str
    total_stops: int
    current_stop_index: int
    expires_at: Optional[datetime] = None
    extended: bool = False
    booked_property_id: Optional[int] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    stops: list[TourStopResponse] = []

    model_config = {"from_attributes": True}
