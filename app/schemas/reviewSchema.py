# HillPing — Review schemas

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    booking_id: int
    rating_cleanliness: int = Field(..., ge=1, le=5)
    rating_accuracy: int = Field(..., ge=1, le=5)
    rating_value: int = Field(..., ge=1, le=5)
    rating_location: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None


class OwnerResponseCreate(BaseModel):
    response: str = Field(..., min_length=1, max_length=2000)


class ReviewResponse(BaseModel):
    id: int
    booking_id: int
    guest_id: int
    property_id: int
    rating_cleanliness: int
    rating_accuracy: int
    rating_value: int
    rating_location: int
    rating_overall: float
    comment: Optional[str] = None
    owner_response: Optional[str] = None
    guest_name: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
