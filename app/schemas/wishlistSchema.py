# HillPing — Wishlist schemas

from datetime import datetime
from pydantic import BaseModel


class WishlistAdd(BaseModel):
    property_id: int


class WishlistResponse(BaseModel):
    id: int
    property_id: int
    created_at: datetime

    model_config = {"from_attributes": True}
