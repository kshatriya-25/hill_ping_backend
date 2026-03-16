# HillPing — Coupon Validation & Application Service

import datetime
from datetime import timezone
from decimal import Decimal

from sqlalchemy.orm import Session
from sqlalchemy import func

from ..modals.coupon import Coupon, CouponUsage


class CouponError(Exception):
    def __init__(self, detail: str):
        self.detail = detail


def validate_coupon(
    code: str,
    user_id: int,
    booking_amount: Decimal,
    property_id: int,
    db: Session,
) -> Coupon:
    """
    Validate a coupon code against all rules.
    Returns the Coupon if valid, raises CouponError otherwise.
    """
    coupon = db.query(Coupon).filter(
        func.upper(Coupon.code) == code.upper()
    ).first()

    if not coupon:
        raise CouponError("Coupon not found. Please check the code.")

    if not coupon.is_active:
        raise CouponError("This coupon is no longer valid")

    now = datetime.datetime.now(timezone.utc)

    if now < coupon.valid_from.replace(tzinfo=timezone.utc):
        raise CouponError("This coupon is not yet active")

    if now > coupon.valid_to.replace(tzinfo=timezone.utc):
        raise CouponError("This coupon has expired")

    # Max total uses
    if coupon.max_uses is not None and coupon.current_uses >= coupon.max_uses:
        raise CouponError("This coupon has been fully redeemed")

    # Per-user limit
    user_uses = db.query(func.count(CouponUsage.id)).filter(
        CouponUsage.coupon_id == coupon.id,
        CouponUsage.user_id == user_id,
    ).scalar() or 0
    if user_uses >= coupon.per_user_limit:
        raise CouponError("You have already used this coupon")

    # Property-specific coupon
    if coupon.property_id is not None and coupon.property_id != property_id:
        raise CouponError("This coupon is not valid for this property")

    # Minimum booking amount
    if coupon.min_booking_amount is not None and booking_amount < coupon.min_booking_amount:
        raise CouponError(f"Minimum booking amount of ₹{coupon.min_booking_amount} required")

    return coupon


def apply_coupon(coupon: Coupon, booking_amount: Decimal) -> Decimal:
    """
    Calculate the discount amount for a coupon.
    Returns the discount (never exceeds booking_amount - 1).
    """
    if coupon.discount_type == "flat":
        discount = coupon.value
    elif coupon.discount_type == "percentage":
        discount = (booking_amount * coupon.value / Decimal("100")).quantize(Decimal("0.01"))
        if coupon.max_cap is not None:
            discount = min(discount, coupon.max_cap)
    else:
        discount = Decimal("0")

    # Discount cannot make amount go below ₹1
    max_discount = booking_amount - Decimal("1")
    discount = min(discount, max_discount)
    discount = max(discount, Decimal("0"))

    return discount


def record_usage(
    coupon_id: int,
    user_id: int,
    booking_id: int,
    discount: Decimal,
    db: Session,
) -> CouponUsage:
    """Record coupon usage and increment counter."""
    usage = CouponUsage(
        coupon_id=coupon_id,
        user_id=user_id,
        booking_id=booking_id,
        discount_applied=discount,
    )
    db.add(usage)

    coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()
    if coupon:
        coupon.current_uses = (coupon.current_uses or 0) + 1

    db.commit()
    db.refresh(usage)
    return usage
