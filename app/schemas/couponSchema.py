# HillPing — Coupon schemas

from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class CouponCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=30)
    discount_type: str = Field(..., pattern=r'^(percentage|flat)$')
    value: Decimal = Field(..., gt=0)
    max_cap: Optional[Decimal] = Field(default=None, ge=0)
    valid_from: datetime
    valid_to: datetime
    max_uses: Optional[int] = Field(default=None, ge=1)
    per_user_limit: int = Field(default=1, ge=1)
    min_booking_amount: Optional[Decimal] = Field(default=None, ge=0)
    property_id: Optional[int] = None  # null = platform-wide

    @field_validator("code")
    @classmethod
    def uppercase_code(cls, v: str) -> str:
        return v.upper().strip()


class CouponUpdate(BaseModel):
    discount_type: Optional[str] = Field(default=None, pattern=r'^(percentage|flat)$')
    value: Optional[Decimal] = Field(default=None, gt=0)
    max_cap: Optional[Decimal] = Field(default=None, ge=0)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    max_uses: Optional[int] = Field(default=None, ge=1)
    per_user_limit: Optional[int] = Field(default=None, ge=1)
    min_booking_amount: Optional[Decimal] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class CouponValidateRequest(BaseModel):
    code: str
    property_id: int
    booking_amount: Decimal = Field(..., gt=0)


class CouponValidateResponse(BaseModel):
    valid: bool
    discount_amount: Decimal = Decimal("0")
    message: str = ""


class CouponResponse(BaseModel):
    id: int
    code: str
    discount_type: str
    value: Decimal
    max_cap: Optional[Decimal] = None
    valid_from: datetime
    valid_to: datetime
    max_uses: Optional[int] = None
    current_uses: int
    per_user_limit: int
    min_booking_amount: Optional[Decimal] = None
    property_id: Optional[int] = None
    is_active: bool
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
