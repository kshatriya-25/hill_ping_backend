# HillPing — Mediator schemas (V2)

from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field


class MediatorRegister(BaseModel):
    """Mediator self-registration (creates User + MediatorProfile)."""
    name: str = Field(..., min_length=1, max_length=100)
    username: str = Field(..., min_length=3, max_length=50, pattern=r'^[a-zA-Z0-9_.\-]+$')
    email: str = Field(..., max_length=255)
    phone: str = Field(..., max_length=15)
    password: str = Field(..., min_length=8)

    mediator_type: str = Field(
        default="freelance_agent",
        pattern=r'^(auto_driver|travel_desk|local_guide|shop_owner|freelance_agent|hotel_front_desk)$',
    )
    operating_zone: Optional[list[dict]] = None
    aadhaar_doc_url: Optional[str] = None
    referral_code: Optional[str] = None  # referrer's code


class MediatorProfileUpdate(BaseModel):
    """Partial update for mediator profile."""
    mediator_type: Optional[str] = Field(
        default=None,
        pattern=r'^(auto_driver|travel_desk|local_guide|shop_owner|freelance_agent|hotel_front_desk)$',
    )
    operating_zone: Optional[list[dict]] = None
    aadhaar_doc_url: Optional[str] = None
    profile_photo_url: Optional[str] = None


class MediatorProfileResponse(BaseModel):
    id: int
    user_id: int
    mediator_type: str
    operating_zone: Optional[list[dict]] = None
    verification_status: str
    verification_note: Optional[str] = None
    badge_issued: bool
    wallet_balance: Decimal
    total_bookings: int
    total_earnings: Decimal
    acquired_guests_count: int
    referral_code: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BulkPingRequest(BaseModel):
    """Mediator pings up to 3 properties simultaneously."""
    property_ids: list[int] = Field(..., min_length=1, max_length=3)
    check_in: Optional[str] = None  # date string YYYY-MM-DD, defaults to today
    check_out: Optional[str] = None  # defaults to tomorrow
    guests_count: Optional[int] = Field(default=1, ge=1, le=20)
    guest_count: Optional[int] = None  # alias accepted from frontend
    guest_id: Optional[int] = None  # registered guest, if any


class MediatorSearchQuery(BaseModel):
    """Search params for mediator property search."""
    latitude: float
    longitude: float
    max_distance_km: float = Field(default=5.0, ge=0.5, le=50.0)
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    guests: int = Field(default=1, ge=1)
    room_type: Optional[str] = None
    instant_confirm_only: bool = False
    limit: int = Field(default=20, ge=1, le=50)


class MediatorDashboard(BaseModel):
    """Dashboard stats for mediator home screen."""
    todays_bookings: int = 0
    pending_payouts: Decimal = Decimal("0")
    this_month_earnings: Decimal = Decimal("0")
    success_rate: float = 0.0
    reliability_score: float = 100.0
    wallet_balance: Decimal = Decimal("0")
