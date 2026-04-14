# HillPing — Booking & Payout schemas

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field, model_validator


class BookingInitiate(BaseModel):
    """Guest starts a booking after ping is accepted."""
    ping_session_id: Optional[int] = None
    property_id: int
    room_id: int
    check_in: date
    check_out: date
    guests_count: int = Field(default=1, ge=1, le=20)
    coupon_code: Optional[str] = None

    @model_validator(mode="after")
    def check_dates(self) -> "BookingInitiate":
        if self.check_out <= self.check_in:
            raise ValueError("check_out must be after check_in")
        return self


class PaymentVerify(BaseModel):
    """Guest submits Razorpay payment details after checkout."""
    booking_ref: str
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class BookingCancel(BaseModel):
    reason: Optional[str] = None


class PriceBreakdownItem(BaseModel):
    date: str
    type: str
    price: Decimal
    owner_price: Optional[Decimal] = None
    extras: Optional[Decimal] = None


class PriceQuote(BaseModel):
    base_amount: Decimal
    service_fee: Decimal
    discount_amount: Decimal = Decimal("0")
    total_amount: Decimal
    nights: int
    breakdown: list[PriceBreakdownItem] = []


class BookingResponse(BaseModel):
    id: int
    booking_ref: str
    property_id: int
    room_id: Optional[int] = None
    guest_id: int
    owner_id: int
    check_in: date
    check_out: date
    guests_count: int
    nights: int
    base_amount: Decimal
    discount_amount: Decimal
    service_fee: Decimal
    total_amount: Decimal
    status: str
    payment_status: str
    razorpay_order_id: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BookingListItem(BaseModel):
    id: int
    booking_ref: str
    property_id: int
    property_name: Optional[str] = None
    check_in: date
    check_out: date
    nights: int
    total_amount: Decimal
    status: str
    payment_status: str
    created_at: Optional[datetime] = None


class PayoutResponse(BaseModel):
    id: int
    owner_id: int
    booking_id: Optional[int] = None
    booking_ref: Optional[str] = None
    gross_amount: Decimal
    commission_amount: Decimal
    net_amount: Decimal
    status: str
    payout_date: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
