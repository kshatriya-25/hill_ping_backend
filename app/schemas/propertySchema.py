# HillPing — Property & Room Pydantic schemas

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field


# ── Amenity ───────────────────────────────────────────────────────────────────

class AmenityCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    icon: Optional[str] = Field(default=None, max_length=50)
    category: Optional[str] = Field(default=None, max_length=50)


class AmenityResponse(BaseModel):
    id: int
    name: str
    icon: Optional[str] = None
    category: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


# ── Room ──────────────────────────────────────────────────────────────────────

class RoomCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    room_type: str = Field(default="double", pattern=r'^(single|double|dormitory|suite)$')
    capacity: int = Field(default=2, ge=1, le=50)
    price_weekday: Decimal = Field(..., ge=0)
    price_weekend: Decimal = Field(..., ge=0)


class RoomUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    room_type: Optional[str] = Field(default=None, pattern=r'^(single|double|dormitory|suite)$')
    capacity: Optional[int] = Field(default=None, ge=1, le=50)
    price_weekday: Optional[Decimal] = Field(default=None, ge=0)
    price_weekend: Optional[Decimal] = Field(default=None, ge=0)
    is_available: Optional[bool] = None


class RoomResponse(BaseModel):
    id: int
    name: str
    room_type: str
    capacity: int
    price_weekday: Decimal
    price_weekend: Decimal
    is_available: bool

    model_config = {"from_attributes": True}


# ── Property Photo ────────────────────────────────────────────────────────────

class PropertyPhotoResponse(BaseModel):
    id: int
    url: str
    is_cover: bool
    display_order: int

    model_config = {"from_attributes": True}


# ── Property ──────────────────────────────────────────────────────────────────

class PropertyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    address: str = Field(..., min_length=1)
    city: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=1, max_length=100)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    property_type: str = Field(default="homestay", pattern=r'^(homestay|hotel|cottage|villa)$')
    cancellation_policy: str = Field(default="flexible", pattern=r'^(flexible|moderate|strict)$')
    amenity_ids: list[int] = Field(default_factory=list)


class PropertyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    address: Optional[str] = Field(default=None, min_length=1)
    city: Optional[str] = Field(default=None, min_length=1, max_length=100)
    state: Optional[str] = Field(default=None, min_length=1, max_length=100)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    property_type: Optional[str] = Field(default=None, pattern=r'^(homestay|hotel|cottage|villa)$')
    cancellation_policy: Optional[str] = Field(default=None, pattern=r'^(flexible|moderate|strict)$')
    amenity_ids: Optional[list[int]] = None


class StatusUpdate(BaseModel):
    status: str = Field(..., pattern=r'^(online|offline|full)$')


class PropertyOwnerInfo(BaseModel):
    id: int
    name: str
    is_verified_owner: bool

    model_config = {"from_attributes": True}


class PropertyResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    address: str
    city: str
    state: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    property_type: str
    cancellation_policy: str
    status: str
    is_verified: bool
    is_instant_confirm: bool
    created_at: datetime
    rooms: list[RoomResponse] = []
    photos: list[PropertyPhotoResponse] = []
    amenities: list[AmenityResponse] = []
    owner: Optional[PropertyOwnerInfo] = None

    model_config = {"from_attributes": True}


class PropertyListItem(BaseModel):
    """Simplified schema for list views — no rooms, just key info."""
    id: int
    name: str
    city: str
    state: Optional[str] = None
    property_type: str
    status: str
    is_verified: bool
    is_instant_confirm: bool
    cover_photo: Optional[str] = None
    price_min: Optional[Decimal] = None
    rating_avg: Optional[float] = None
    owner_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_km: Optional[float] = None

    model_config = {"from_attributes": True}


# ── Date Block ────────────────────────────────────────────────────────────────

class DateBlockCreate(BaseModel):
    room_id: Optional[int] = None
    block_date: date
    reason: Optional[str] = Field(default=None, pattern=r'^(offline_booking|maintenance|personal)$')


class DateBlockResponse(BaseModel):
    id: int
    property_id: int
    room_id: Optional[int] = None
    block_date: date
    reason: Optional[str] = None

    model_config = {"from_attributes": True}
