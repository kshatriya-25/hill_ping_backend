# HillPing — Ping Session schemas

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field


class PingRequest(BaseModel):
    """Guest initiates an availability check."""
    property_id: int
    room_id: Optional[int] = None
    check_in: date
    check_out: date
    guests_count: int = Field(default=1, ge=1, le=20)


class PingResponse(BaseModel):
    """Owner responds to a ping."""
    action: str = Field(..., min_length=1, max_length=20)


class PingSessionResponse(BaseModel):
    id: int
    session_id: str
    property_id: int
    room_id: Optional[int] = None
    guest_id: int
    owner_id: int
    check_in: date
    check_out: date
    guests_count: int
    requested_amount: Optional[Decimal] = None
    status: str
    owner_response_time: Optional[float] = None
    # V2: Mediator fields
    mediator_id: Optional[int] = None
    ping_type: str = "single"
    bulk_ping_group_id: Optional[str] = None
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    # Populated for accepted pings (guest total; room flat mediator × nights)
    total_price: Optional[float] = None
    mediator_commission: Optional[float] = None

    model_config = {"from_attributes": True}


class PingStatusResponse(BaseModel):
    """Lightweight status for guest polling."""
    session_id: str
    status: str
    remaining_seconds: int
    property_name: Optional[str] = None
