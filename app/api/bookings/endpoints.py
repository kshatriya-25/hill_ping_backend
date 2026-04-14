# HillPing — Booking endpoints

import datetime
import logging
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from ...database.session import getdb
from ...modals.masters import User
from ...modals.booking import Booking, Payout
from ...modals.property import Property, Room
from ...modals.ping import PingSession
from ...schemas.bookingSchema import (
    BookingInitiate, PaymentVerify, BookingCancel,
    BookingResponse, BookingListItem, PriceQuote,
)
from ...services.pricing import calculate_booking_price
from ...services.payment import (
    create_razorpay_order,
    capture_payment,
    refund_payment,
    verify_payment_signature,
)
from ...core.config import settings
from ...utils.utils import get_current_user, require_guest, require_owner, require_admin

router = APIRouter(tags=["bookings"])


def _generate_booking_ref() -> str:
    """Generate a human-readable booking reference like HP-A1B2C3."""
    return f"HP-{uuid.uuid4().hex[:6].upper()}"


# ── Initiate booking ──────────────────────────────────────────────────────────

@router.post("/initiate", response_model=BookingResponse)
def initiate_booking(
    data: BookingInitiate,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_guest),
):
    """
    Guest initiates a booking after ping acceptance (or instant confirm).
    Creates a Razorpay order for payment authorization.
    """
    # Validate property & room
    prop = db.query(Property).filter(Property.id == data.property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    room = db.query(Room).filter(
        Room.id == data.room_id, Room.property_id == data.property_id
    ).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Validate ping was accepted (if provided)
    if data.ping_session_id:
        ping = db.query(PingSession).filter(
            PingSession.id == data.ping_session_id,
            PingSession.guest_id == current_user.id,
            PingSession.status == "accepted",
        ).first()
        if not ping:
            raise HTTPException(status_code=400, detail="No accepted ping session found")

    # Calculate price (per-property commission; nightly guest total incl. room fees)
    pricing = calculate_booking_price(
        room,
        data.check_in,
        data.check_out,
        commission_override=prop.commission_override,
        commission_type=getattr(prop, "commission_type", None) or "percentage",
    )

    # TODO: Apply coupon if provided (Phase 8)
    discount = Decimal("0")

    total = pricing["total_amount"] - discount
    if total < Decimal("1"):
        total = Decimal("1")  # Minimum transaction

    # Create Razorpay order
    booking_ref = _generate_booking_ref()
    try:
        rz_order = create_razorpay_order(total, booking_ref)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Payment gateway error: {str(e)}")

    # Create booking record
    booking = Booking(
        booking_ref=booking_ref,
        property_id=data.property_id,
        room_id=data.room_id,
        guest_id=current_user.id,
        owner_id=prop.owner_id,
        ping_session_id=data.ping_session_id,
        check_in=data.check_in,
        check_out=data.check_out,
        guests_count=data.guests_count,
        nights=pricing["nights"],
        base_amount=pricing["base_amount"],
        discount_amount=discount,
        service_fee=pricing["service_fee"],
        total_amount=total,
        status="pending",
        razorpay_order_id=rz_order["id"],
        payment_status="pending",
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    return booking


# ── Verify payment ────────────────────────────────────────────────────────────

@router.post("/verify-payment", response_model=BookingResponse)
def verify_payment(
    data: PaymentVerify,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_guest),
):
    """
    Guest submits Razorpay payment details after completing checkout.
    Verifies the signature and marks payment as authorized.
    On confirmation, payment is captured and booking is confirmed.
    """
    booking = db.query(Booking).filter(
        Booking.booking_ref == data.booking_ref,
        Booking.guest_id == current_user.id,
    ).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.payment_status != "pending":
        raise HTTPException(status_code=400, detail=f"Payment already {booking.payment_status}")

    # Verify signature
    if not verify_payment_signature(data.razorpay_order_id, data.razorpay_payment_id, data.razorpay_signature):
        raise HTTPException(status_code=400, detail="Payment signature verification failed")

    booking.razorpay_payment_id = data.razorpay_payment_id
    booking.razorpay_signature = data.razorpay_signature
    booking.payment_status = "authorized"

    # If the ping was already accepted, capture immediately
    if booking.ping_session_id:
        ping = db.query(PingSession).filter(PingSession.id == booking.ping_session_id).first()
        if ping and ping.status == "accepted":
            _capture_and_confirm(booking, db)
    else:
        # Instant confirm path — capture immediately
        _capture_and_confirm(booking, db)

    db.commit()
    db.refresh(booking)
    return booking


# ── Price quote ───────────────────────────────────────────────────────────────

@router.get("/price-quote", response_model=PriceQuote)
def get_price_quote(
    room_id: int,
    check_in: str,
    check_out: str,
    db: Session = Depends(getdb),
):
    """Public: get a price breakdown for a room and date range."""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    prop = db.query(Property).filter(Property.id == room.property_id).first()

    from datetime import date as date_type
    try:
        ci = date_type.fromisoformat(check_in)
        co = date_type.fromisoformat(check_out)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format (use YYYY-MM-DD)")

    try:
        pricing = calculate_booking_price(
            room,
            ci,
            co,
            commission_override=prop.commission_override if prop else None,
            commission_type=getattr(prop, "commission_type", None) or "percentage",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PriceQuote(
        base_amount=pricing["base_amount"],
        service_fee=pricing["service_fee"],
        total_amount=pricing["total_amount"],
        nights=pricing["nights"],
        breakdown=pricing["breakdown"],
    )


# ── Guest bookings ────────────────────────────────────────────────────────────

@router.get("/my", response_model=list[BookingListItem])
def my_bookings(
    status: str = Query(default=None),
    db: Session = Depends(getdb),
    current_user: User = Depends(require_guest),
):
    """Guest views their bookings."""
    q = db.query(Booking).filter(Booking.guest_id == current_user.id)
    if status:
        q = q.filter(Booking.status == status)
    bookings = q.order_by(Booking.created_at.desc()).all()

    result = []
    for b in bookings:
        prop = db.query(Property).filter(Property.id == b.property_id).first()
        result.append(BookingListItem(
            id=b.id,
            booking_ref=b.booking_ref,
            property_id=b.property_id,
            property_name=prop.name if prop else None,
            check_in=b.check_in,
            check_out=b.check_out,
            nights=b.nights,
            total_amount=b.total_amount,
            status=b.status,
            payment_status=b.payment_status,
            created_at=b.created_at,
        ))
    return result


# ── Owner bookings ────────────────────────────────────────────────────────────

@router.get("/owner", response_model=list[BookingListItem])
def owner_bookings(
    status: str = Query(default=None),
    db: Session = Depends(getdb),
    current_user: User = Depends(require_owner),
):
    """Owner views bookings for their properties."""
    q = db.query(Booking).filter(Booking.owner_id == current_user.id)
    if status:
        q = q.filter(Booking.status == status)
    bookings = q.order_by(Booking.created_at.desc()).all()

    result = []
    for b in bookings:
        prop = db.query(Property).filter(Property.id == b.property_id).first()
        result.append(BookingListItem(
            id=b.id,
            booking_ref=b.booking_ref,
            property_id=b.property_id,
            property_name=prop.name if prop else None,
            check_in=b.check_in,
            check_out=b.check_out,
            nights=b.nights,
            total_amount=b.total_amount,
            status=b.status,
            payment_status=b.payment_status,
            created_at=b.created_at,
        ))
    return result


# ── Booking detail ────────────────────────────────────────────────────────────

@router.get("/{booking_id}", response_model=BookingResponse)
def get_booking(
    booking_id: int,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """View a specific booking."""
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if current_user.role != "admin" and current_user.id not in (booking.guest_id, booking.owner_id):
        raise HTTPException(status_code=403, detail="Not authorized")
    return booking


# ── Cancel booking ────────────────────────────────────────────────────────────

@router.post("/{booking_id}/cancel", response_model=BookingResponse)
def cancel_booking(
    booking_id: int,
    data: BookingCancel,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Guest or owner cancels a booking."""
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    is_guest = current_user.id == booking.guest_id
    is_owner = current_user.id == booking.owner_id
    if not is_guest and not is_owner and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    if booking.status in ("cancelled_by_guest", "cancelled_by_owner", "completed"):
        raise HTTPException(status_code=400, detail=f"Booking already {booking.status}")

    now = datetime.datetime.now(datetime.timezone.utc)
    booking.status = "cancelled_by_guest" if is_guest else "cancelled_by_owner"
    booking.cancellation_reason = data.reason
    booking.cancelled_at = now

    # Refund if payment was captured
    if booking.payment_status == "captured" and booking.razorpay_payment_id:
        try:
            refund_payment(booking.razorpay_payment_id, booking.total_amount)
            booking.payment_status = "refunded"
        except Exception:
            pass  # Log and handle manually

    # If owner cancelled, update reliability
    if is_owner:
        from ...services.ping import _recalculate_owner_score
        _recalculate_owner_score(booking.owner_id, db)

    db.commit()
    db.refresh(booking)
    return booking


# ── Mark complete ─────────────────────────────────────────────────────────────

@router.post("/{booking_id}/complete", response_model=BookingResponse)
def complete_booking(
    booking_id: int,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Mark a booking as completed (after checkout)."""
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    is_owner = current_user.id == booking.owner_id
    if not is_owner and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    if booking.status != "confirmed":
        raise HTTPException(status_code=400, detail="Only confirmed bookings can be completed")

    booking.status = "completed"

    # Create payout record
    commission_rate = Decimal(str(settings.COMMISSION_PERCENTAGE)) / Decimal("100")
    commission = (booking.total_amount * commission_rate).quantize(Decimal("0.01"))
    net = booking.total_amount - commission

    payout = Payout(
        owner_id=booking.owner_id,
        booking_id=booking.id,
        gross_amount=booking.total_amount,
        commission_amount=commission,
        net_amount=net,
        status="pending",
    )
    db.add(payout)

    # V2: Mediator commission calculation
    if booking.mediator_id:
        from ...services.mediator_commission import (
            calculate_booking_commission, check_residual_commission, record_guest_acquisition,
        )
        from ...services.mediator_reliability import calculate_mediator_score

        calculate_booking_commission(booking, booking.mediator_id, db)
        record_guest_acquisition(booking.mediator_id, booking.guest_id, booking.id, db)
        calculate_mediator_score(booking.mediator_id, db)
    else:
        # Check residual commission for acquired guests booking directly
        from ...services.mediator_commission import check_residual_commission
        check_residual_commission(booking, db)

    db.commit()
    db.refresh(booking)
    return booking


# ── Internal helpers ──────────────────────────────────────────────────────────

def _capture_and_confirm(booking: Booking, db: Session):
    """Capture payment and confirm booking. Also creates Trip Card."""
    if booking.razorpay_payment_id:
        try:
            capture_payment(booking.razorpay_payment_id, booking.total_amount)
            booking.payment_status = "captured"
            booking.status = "confirmed"

            # V2: Auto-create Trip Card on booking confirmation
            try:
                from ...services.trip_card import create_trip_card
                create_trip_card(booking.id, db)
            except Exception as e:
                logger = logging.getLogger(__name__)
                logger.error("Failed to create trip card for booking %s: %s", booking.booking_ref, e)

        except Exception:
            booking.payment_status = "failed"
            booking.status = "pending"
