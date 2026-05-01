# HillPing — Admin Dashboard endpoints

import datetime
import json
from datetime import timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import case, func

from ...database.session import getdb
from ...modals.masters import User
from ...modals.property import Property, Room, PropertyPhoto, PropertyAmenity, Amenity
from ...modals.booking import Booking, Payout
from ...modals.ping import PingSession
from ...modals.reliability import OwnerReliabilityScore, OwnerPenalty
from ...modals.review import Review
from ...modals.coupon import Coupon
from ...schemas.propertySchema import PropertyListItem
from ...schemas.reliabilitySchema import ReliabilityScoreResponse
from ...utils.utils import require_admin
from ...services.platform_config import get_all_config, set_config, reset_config, DEFAULTS, LIST_KEYS
from ...services.pricing import room_min_guest_nightly


class ConfigUpdateBody(BaseModel):
    value: Any

router = APIRouter(tags=["admin"])


# ── Dashboard overview ────────────────────────────────────────────────────────

@router.get("/dashboard")
def dashboard_overview(
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Platform-wide stats."""
    total_properties = db.query(func.count(Property.id)).scalar() or 0
    online_properties = db.query(func.count(Property.id)).filter(Property.status == "online").scalar() or 0
    total_owners = db.query(func.count(User.id)).filter(User.role == "owner").scalar() or 0
    total_guests = db.query(func.count(User.id)).filter(User.role == "guest").scalar() or 0
    total_bookings = db.query(func.count(Booking.id)).scalar() or 0
    confirmed_bookings = db.query(func.count(Booking.id)).filter(Booking.status == "confirmed").scalar() or 0
    completed_bookings = db.query(func.count(Booking.id)).filter(Booking.status == "completed").scalar() or 0

    gross_revenue = db.query(func.sum(Booking.total_amount)).filter(
        Booking.payment_status == "captured"
    ).scalar() or Decimal("0")

    platform_commission = db.query(func.sum(Payout.commission_amount)).scalar() or Decimal("0")
    pending_payouts = db.query(func.sum(Payout.net_amount)).filter(
        Payout.status == "pending"
    ).scalar() or Decimal("0")

    total_reviews = db.query(func.count(Review.id)).scalar() or 0
    avg_rating = db.query(func.avg(Review.rating_overall)).scalar() or 0

    active_coupons = db.query(func.count(Coupon.id)).filter(Coupon.is_active == True).scalar() or 0

    # V2: Mediator stats
    from ...modals.mediator import MediatorProfile
    from ...modals.mediator_commission import MediatorCommission

    total_mediators = db.query(func.count(User.id)).filter(User.role == "mediator").scalar() or 0
    verified_mediators = db.query(func.count(MediatorProfile.id)).filter(
        MediatorProfile.verification_status == "verified"
    ).scalar() or 0
    pending_mediators = db.query(func.count(MediatorProfile.id)).filter(
        MediatorProfile.verification_status == "pending"
    ).scalar() or 0

    mediator_bookings = db.query(func.count(Booking.id)).filter(
        Booking.mediator_id.isnot(None),
    ).scalar() or 0

    total_mediator_commission = db.query(func.sum(MediatorCommission.commission_amount)).filter(
        MediatorCommission.status.in_(["pending", "approved", "paid"]),
    ).scalar() or Decimal("0")

    return {
        "properties": {
            "total": total_properties,
            "online": online_properties,
        },
        "users": {
            "owners": total_owners,
            "guests": total_guests,
            "mediators": total_mediators,
            "mediators_verified": verified_mediators,
            "mediators_pending": pending_mediators,
        },
        "bookings": {
            "total": total_bookings,
            "confirmed": confirmed_bookings,
            "completed": completed_bookings,
        },
        "revenue": {
            "gross": float(gross_revenue),
            "platform_commission": float(platform_commission),
            "pending_payouts": float(pending_payouts),
        },
        "reviews": {
            "total": total_reviews,
            "avg_rating": round(float(avg_rating), 2),
        },
        "active_coupons": active_coupons,
        "mediators": {
            "total_mediator_bookings": mediator_bookings,
            "total_mediator_commission": float(total_mediator_commission),
        },
    }


# ── Property management ──────────────────────────────────────────────────────

@router.get("/properties")
def admin_list_properties(
    status: str = Query(default=None),
    verified: bool = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin lists all properties with filters."""
    q = db.query(Property)
    if status:
        q = q.filter(Property.status == status)
    if verified is not None:
        q = q.filter(Property.is_verified == verified)

    total = q.count()
    properties = q.order_by(Property.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for p in properties:
        # Rooms summary
        rooms = db.query(Room).filter(Room.property_id == p.id).all()
        min_price = min((float(room_min_guest_nightly(r)) for r in rooms), default=None) if rooms else None
        total_capacity = sum(r.capacity * (getattr(r, "total_rooms", None) or 1) for r in rooms)

        # Photos
        photos = db.query(PropertyPhoto).filter(PropertyPhoto.property_id == p.id).order_by(PropertyPhoto.display_order).all()
        cover = next((ph for ph in photos if ph.is_cover), photos[0] if photos else None)

        # Amenities
        amenity_links = db.query(PropertyAmenity).filter(PropertyAmenity.property_id == p.id).all()
        amenity_names = []
        for link in amenity_links:
            a = db.query(Amenity).filter(Amenity.id == link.amenity_id).first()
            if a:
                amenity_names.append(a.name)

        # Bookings count
        booking_count = db.query(func.count(Booking.id)).filter(Booking.property_id == p.id).scalar() or 0

        result.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "address": p.address,
            "city": p.city,
            "state": p.state,
            "property_type": p.property_type,
            "cancellation_policy": p.cancellation_policy,
            "status": p.status,
            "is_verified": p.is_verified,
            "is_instant_confirm": p.is_instant_confirm,
            "owner_id": p.owner_id,
            "owner_name": p.owner.name if p.owner else None,
            "created_at": p.created_at,
            "rooms_count": len(rooms),
            "total_capacity": total_capacity,
            "price_min": min_price,
            "photos_count": len(photos),
            "cover_photo": cover.url if cover else None,
            "amenities": amenity_names,
            "commission_override": p.commission_override,
            "commission_type": p.commission_type,
            "booking_count": booking_count,
            "rooms": [
                {
                    "id": r.id,
                    "name": r.name,
                    "room_type": r.room_type,
                    "capacity": r.capacity,
                    "total_rooms": getattr(r, "total_rooms", None) or 1,
                    "price_weekday": float(r.price_weekday),
                    "price_weekend": float(r.price_weekend),
                    "weekend_days": getattr(r, "weekend_days", None),
                    "mediator_commission": (
                        float(mc)
                        if (mc := getattr(r, "mediator_commission", None)) is not None
                        else None
                    ),
                    "platform_fee": (
                        float(pf)
                        if (pf := getattr(r, "platform_fee", None)) is not None
                        else None
                    ),
                    "is_available": r.is_available,
                }
                for r in rooms
            ],
        })

    return {
        "total": total,
        "properties": result,
    }


@router.patch("/properties/{property_id}/commission")
def set_property_commission(
    property_id: int,
    commission: float = Query(None, ge=0, description="Commission value (null to reset to global)"),
    commission_type: str = Query("percentage", pattern=r'^(percentage|fixed)$', description="percentage or fixed"),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin sets per-property commission override. Pass null commission to reset to global."""
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    prop.commission_override = commission
    prop.commission_type = commission_type if commission is not None else "percentage"
    db.commit()
    label = "reset to global" if commission is None else (
        f"set to ₹{commission} fixed" if commission_type == "fixed" else f"set to {commission}%"
    )
    return {
        "detail": f"Commission {label}",
        "property_id": property_id,
        "commission_override": commission,
        "commission_type": prop.commission_type,
    }


@router.patch("/properties/{property_id}/verify")
def verify_property(
    property_id: int,
    verified: bool = True,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin verifies or unverifies a property."""
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    prop.is_verified = verified
    db.commit()
    return {"detail": f"Property {'verified' if verified else 'unverified'}"}


# ── User management ──────────────────────────────────────────────────────────

@router.patch("/users/{user_id}/role")
def change_user_role(
    user_id: int,
    role: str = Query(..., pattern=r'^(guest|owner|mediator|admin)$'),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin changes a user's role. Auto-creates MediatorProfile if switching to mediator."""
    import secrets
    import string
    from ...modals.mediator import MediatorProfile

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = role

    # When role changes to mediator, ensure a MediatorProfile exists
    if role == "mediator":
        existing_profile = db.query(MediatorProfile).filter(
            MediatorProfile.user_id == user_id
        ).first()
        if not existing_profile:
            # Generate unique referral code
            def _gen_code():
                chars = string.ascii_uppercase + string.digits
                return "HP-" + "".join(secrets.choice(chars) for _ in range(8))

            referral_code = _gen_code()
            while db.query(MediatorProfile).filter(
                MediatorProfile.referral_code == referral_code
            ).first():
                referral_code = _gen_code()

            profile = MediatorProfile(
                user_id=user_id,
                mediator_type="freelance_agent",
                verification_status="verified",
                referral_code=referral_code,
            )
            db.add(profile)

    db.commit()
    return {"detail": f"User {user_id} role changed to {role}"}


# ── Reliability management ────────────────────────────────────────────────────

@router.get("/reliability/at-risk", response_model=list[ReliabilityScoreResponse])
def at_risk_owners(
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin views owners with score below 50."""
    return db.query(OwnerReliabilityScore).filter(
        OwnerReliabilityScore.total_score < 50
    ).order_by(OwnerReliabilityScore.total_score.asc()).all()


@router.post("/reliability/suspend/{owner_id}")
def suspend_owner(
    owner_id: int,
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin manually suspends an owner."""
    now = datetime.datetime.now(timezone.utc)
    suspended_until = now + datetime.timedelta(days=days)

    score = db.query(OwnerReliabilityScore).filter(
        OwnerReliabilityScore.owner_id == owner_id
    ).first()
    if score:
        score.is_suspended = True
        score.suspended_until = suspended_until

    # Set all properties offline
    db.query(Property).filter(Property.owner_id == owner_id).update({"status": "offline"})

    # Record penalty
    penalty = OwnerPenalty(
        owner_id=owner_id,
        penalty_type="suspension",
        reason=f"Manual admin suspension for {days} days",
        expires_at=suspended_until,
    )
    db.add(penalty)
    db.commit()

    return {"detail": f"Owner {owner_id} suspended for {days} days"}


@router.post("/reliability/unsuspend/{owner_id}")
def unsuspend_owner(
    owner_id: int,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin lifts suspension."""
    score = db.query(OwnerReliabilityScore).filter(
        OwnerReliabilityScore.owner_id == owner_id
    ).first()
    if score:
        score.is_suspended = False
        score.suspended_until = None

    db.query(OwnerPenalty).filter(
        OwnerPenalty.owner_id == owner_id,
        OwnerPenalty.penalty_type.in_(["suspension", "delist"]),
        OwnerPenalty.is_active == True,
    ).update({"is_active": False}, synchronize_session="fetch")

    db.commit()
    return {"detail": f"Owner {owner_id} unsuspended"}


# ── Create booking from accepted ping (admin shortcut) ───────────────────────

@router.post("/bookings/from-ping")
def admin_create_booking_from_ping(
    session_id: str = Query(..., description="Accepted ping session_id"),
    payment_mode: str = Query(default="pay_at_property"),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """
    Admin creates a confirmed booking directly from an accepted ping session.
    Picks the best-fit room automatically (lowest price that fits guests_count).
    No payment required — booking is immediately confirmed.
    """
    from ...modals.ping import PingSession
    from ...modals.property import Room
    from ...services.pricing import calculate_booking_price
    import uuid

    ping = db.query(PingSession).filter(PingSession.session_id == session_id).first()
    if not ping:
        raise HTTPException(status_code=404, detail="Ping session not found")
    if ping.status != "accepted":
        raise HTTPException(status_code=400, detail="Ping is not in accepted state")

    # Pick room: prefer the one on the ping, else cheapest that fits guest count
    room = None
    if ping.room_id:
        room = db.query(Room).filter(Room.id == ping.room_id, Room.property_id == ping.property_id).first()
    if not room:
        guest_floor = (
            Room.price_weekday
            + func.coalesce(Room.mediator_commission, 0)
            + func.coalesce(Room.platform_fee, 0)
        )
        room = (
            db.query(Room)
            .filter(Room.property_id == ping.property_id, Room.capacity >= ping.guests_count, Room.is_available == True)
            .order_by(guest_floor.asc())
            .first()
        )
    if not room:
        raise HTTPException(status_code=400, detail="No suitable room available for this property")

    prop = db.query(Property).filter(Property.id == ping.property_id).first()
    pricing = calculate_booking_price(
        room,
        ping.check_in,
        ping.check_out,
        commission_override=prop.commission_override if prop else None,
        commission_type=getattr(prop, "commission_type", None) or "percentage",
    )

    booking_ref = f"HP-{uuid.uuid4().hex[:6].upper()}"
    booking = Booking(
        booking_ref=booking_ref,
        property_id=ping.property_id,
        room_id=room.id,
        guest_id=ping.guest_id,
        owner_id=ping.owner_id,
        mediator_id=ping.mediator_id,
        ping_session_id=ping.id,
        check_in=ping.check_in,
        check_out=ping.check_out,
        guests_count=ping.guests_count,
        nights=pricing["nights"],
        base_amount=pricing["base_amount"],
        discount_amount=0,
        service_fee=pricing["service_fee"],
        total_amount=pricing["total_amount"],
        status="confirmed",
        payment_mode=payment_mode,
        payment_status="pending",
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    guest = db.query(User).filter(User.id == ping.guest_id).first()
    prop = db.query(Property).filter(Property.id == ping.property_id).first()

    return {
        "booking_ref": booking.booking_ref,
        "booking_id": booking.id,
        "property_name": prop.name if prop else "",
        "room_name": room.name,
        "guest_name": guest.name if guest else "",
        "total_amount": float(booking.total_amount),
        "check_in": str(booking.check_in),
        "check_out": str(booking.check_out),
        "nights": booking.nights,
        "status": booking.status,
    }


# ── Booking overview ──────────────────────────────────────────────────────────

@router.get("/bookings")
def admin_list_bookings(
    status: str = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin lists all bookings with mediator & commission info."""
    from ...modals.mediator_commission import MediatorCommission

    q = db.query(Booking)
    if status:
        q = q.filter(Booking.status == status)
    total = q.count()
    bookings = q.order_by(Booking.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for b in bookings:
        # Mediator info
        mediator = db.query(User).filter(User.id == b.mediator_id).first() if b.mediator_id else None
        guest = db.query(User).filter(User.id == b.guest_id).first()
        prop = db.query(Property).filter(Property.id == b.property_id).first()

        # Commission status for this booking
        commission = db.query(MediatorCommission).filter(
            MediatorCommission.booking_id == b.id,
            MediatorCommission.commission_type == "booking",
        ).first() if b.mediator_id else None

        # Owner payout status
        payout = db.query(Payout).filter(Payout.booking_id == b.id).first()

        result.append({
            "id": b.id,
            "booking_ref": b.booking_ref,
            "property_id": b.property_id,
            "property_name": prop.name if prop else None,
            "guest_id": b.guest_id,
            "guest_name": guest.name if guest else None,
            "guest_phone": guest.phone if guest else None,
            "owner_id": b.owner_id,
            "mediator_id": b.mediator_id,
            "mediator_name": mediator.name if mediator else None,
            "mediator_phone": mediator.phone if mediator else None,
            "check_in": str(b.check_in),
            "check_out": str(b.check_out),
            "total_amount": float(b.total_amount),
            "status": b.status,
            "payment_status": b.payment_status,
            "payment_mode": b.payment_mode,
            "commission": {
                "id": commission.id,
                "amount": float(commission.commission_amount),
                "rate": commission.commission_rate,
                "status": commission.status,
            } if commission else None,
            "owner_payout": {
                "id": payout.id,
                "gross": float(payout.gross_amount),
                "commission": float(payout.commission_amount),
                "net": float(payout.net_amount),
                "status": payout.status,
            } if payout else None,
            "created_at": b.created_at,
        })

    return {"total": total, "bookings": result}


@router.post("/bookings/{booking_id}/credit-commission")
def credit_commission(
    booking_id: int,
    amount: float = Query(None, ge=0, description="Custom amount (null = use calculated)"),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """
    Admin credits commission to mediator for a confirmed booking.
    Creates commission record if none exists, or approves existing pending one.
    """
    from ...modals.mediator_commission import MediatorCommission
    from ...modals.mediator import MediatorProfile

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if not booking.mediator_id:
        raise HTTPException(status_code=400, detail="This booking has no mediator")

    # Check for existing commission
    existing = db.query(MediatorCommission).filter(
        MediatorCommission.booking_id == booking_id,
        MediatorCommission.commission_type == "booking",
    ).first()

    if existing and existing.status in ("approved", "paid"):
        raise HTTPException(status_code=400, detail=f"Commission already {existing.status}")

    if existing:
        # Update amount if custom, then approve
        if amount is not None:
            existing.commission_amount = Decimal(str(amount))
        existing.status = "approved"
        existing.payout_date = datetime.datetime.now(timezone.utc)
        commission_amount = float(existing.commission_amount)
    else:
        # Create new commission record
        if amount is not None:
            commission_amount = amount
            rate = round(amount / max(float(booking.total_amount), 1) * 100, 2)
        else:
            # Use tiered calculation
            from ...services.mediator_commission import calculate_booking_commission
            new_commission = calculate_booking_commission(booking, booking.mediator_id, db)
            if new_commission:
                new_commission.status = "approved"
                new_commission.payout_date = datetime.datetime.now(timezone.utc)
                commission_amount = float(new_commission.commission_amount)
                db.commit()
                # Update mediator profile earnings
                profile = db.query(MediatorProfile).filter(
                    MediatorProfile.user_id == booking.mediator_id
                ).first()
                if profile:
                    profile.total_earnings += new_commission.commission_amount
                    profile.wallet_balance += new_commission.commission_amount
                    profile.total_bookings += 1
                    db.commit()
                return {
                    "detail": f"Commission ₹{commission_amount} credited to mediator",
                    "commission_amount": commission_amount,
                    "status": "approved",
                }
            raise HTTPException(status_code=500, detail="Failed to calculate commission")

        existing_obj = MediatorCommission(
            mediator_id=booking.mediator_id,
            booking_id=booking_id,
            guest_id=booking.guest_id,
            commission_type="booking",
            booking_amount=booking.total_amount,
            commission_rate=rate,
            commission_amount=Decimal(str(commission_amount)),
            status="approved",
            payout_date=datetime.datetime.now(timezone.utc),
        )
        db.add(existing_obj)

    # Update mediator profile earnings
    profile = db.query(MediatorProfile).filter(
        MediatorProfile.user_id == booking.mediator_id
    ).first()
    if profile:
        profile.total_earnings += Decimal(str(commission_amount))
        profile.wallet_balance += Decimal(str(commission_amount))
        profile.total_bookings += 1

    db.commit()

    # Send push notification to mediator
    from ...services.notifications import send_push_to_user
    prop = db.query(Property).filter(Property.id == booking.property_id).first()
    send_push_to_user(
        user_id=booking.mediator_id,
        title="Commission Credited!",
        body=f"₹{commission_amount} earned for booking at {prop.name if prop else 'a property'}",
        data={
            "type": "earnings_credited",
            "amount": str(commission_amount),
            "booking_id": str(booking_id),
            "property_name": prop.name if prop else "",
        },
        db=db,
    )

    return {
        "detail": f"Commission ₹{commission_amount} credited to mediator",
        "commission_amount": commission_amount,
        "status": "approved",
    }


@router.post("/bookings/{booking_id}/credit-owner")
def credit_owner(
    booking_id: int,
    net_amount: float = Query(None, ge=0, description="Custom net amount (null = auto-calc from booking minus commission)"),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """
    Admin credits earnings to property owner for a booking.
    Creates a Payout record. Auto-calculates: gross - platform commission = net.
    """
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Check for existing payout
    existing = db.query(Payout).filter(Payout.booking_id == booking_id).first()
    if existing:
        if existing.status == "processed":
            raise HTTPException(status_code=400, detail="Owner already paid for this booking")
        # If pending, process it
        existing.status = "processed"
        existing.payout_date = datetime.datetime.now(timezone.utc)
        if net_amount is not None:
            existing.net_amount = Decimal(str(net_amount))
        db.commit()

        from ...services.notifications import send_push_to_user
        prop = db.query(Property).filter(Property.id == booking.property_id).first()
        send_push_to_user(
            user_id=booking.owner_id,
            title="Payment Credited!",
            body=f"₹{float(existing.net_amount)} received for booking at {prop.name if prop else 'your property'}",
            data={
                "type": "earnings_credited",
                "amount": str(float(existing.net_amount)),
                "booking_id": str(booking_id),
                "property_name": prop.name if prop else "",
            },
            db=db,
        )
        return {
            "detail": f"₹{float(existing.net_amount)} credited to owner",
            "net_amount": float(existing.net_amount),
            "status": "processed",
        }

    # Calculate amounts
    gross = float(booking.total_amount)
    prop = db.query(Property).filter(Property.id == booking.property_id).first()

    if net_amount is not None:
        commission_amt = gross - net_amount
    else:
        # Use property commission override or global
        commission_pct = prop.commission_override if (prop and prop.commission_override is not None) else float(settings.COMMISSION_PERCENTAGE)
        if prop and prop.commission_type == "fixed" and prop.commission_override is not None:
            commission_amt = prop.commission_override
        else:
            commission_amt = round(gross * commission_pct / 100, 2)
        net_amount = gross - commission_amt

    payout = Payout(
        owner_id=booking.owner_id,
        booking_id=booking_id,
        gross_amount=Decimal(str(gross)),
        commission_amount=Decimal(str(commission_amt)),
        net_amount=Decimal(str(net_amount)),
        status="processed",
        payout_date=datetime.datetime.now(timezone.utc),
    )
    db.add(payout)
    db.commit()

    # Send push notification to owner
    from ...services.notifications import send_push_to_user
    send_push_to_user(
        user_id=booking.owner_id,
        title="Payment Credited!",
        body=f"₹{net_amount} received for booking at {prop.name if prop else 'your property'}",
        data={
            "type": "earnings_credited",
            "amount": str(net_amount),
            "booking_id": str(booking_id),
            "property_name": prop.name if prop else "",
        },
        db=db,
    )

    return {
        "detail": f"₹{net_amount} credited to owner (commission: ₹{commission_amt})",
        "gross_amount": gross,
        "commission_amount": commission_amt,
        "net_amount": net_amount,
        "status": "processed",
    }


# ── Platform Configuration ────────────────────────────────────────────────────

@router.get("/config")
def get_platform_config(
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """
    Admin views all platform configuration.
    Returns each key with its current value, default, whether it's been
    customised, and a human-readable description.
    """
    return get_all_config(db)


@router.patch("/config/{key}")
def update_platform_config(
    key: str,
    body: ConfigUpdateBody,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin updates a single platform config key. Body: { "value": <string or array> }"""
    if key not in DEFAULTS:
        raise HTTPException(status_code=400, detail=f"Unknown config key: {key}. Valid keys: {list(DEFAULTS.keys())}")

    if key in LIST_KEYS:
        if not isinstance(body.value, list):
            raise HTTPException(status_code=400, detail="Value must be a JSON array for list config keys")
        store_value = json.dumps(body.value)
    else:
        str_value = str(body.value)
        try:
            float(str_value)
        except ValueError:
            raise HTTPException(status_code=400, detail="Value must be numeric")
        store_value = str_value

    set_config(key, store_value, db)
    return {
        "key": key,
        "value": body.value,
        "detail": f"Config '{key}' updated",
    }


@router.delete("/config/{key}")
def reset_platform_config(
    key: str,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin resets a config key to its default value."""
    if key not in DEFAULTS:
        raise HTTPException(status_code=400, detail=f"Unknown config key: {key}")

    reset_config(key, db)
    return {
        "key": key,
        "value": DEFAULTS[key],
        "detail": f"Config '{key}' reset to default: {DEFAULTS[key]}",
    }


# ── V2: Mediator management ──────────────────────────────────────────────────

@router.post("/mediators/create")
def admin_create_mediator(
    name: str = Query(...),
    username: str = Query(...),
    email: str = Query(...),
    phone: str = Query(...),
    password: str = Query(...),
    mediator_type: str = Query(default="freelance_agent"),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin creates a mediator directly (pre-verified, no KYC wait)."""
    import secrets
    import string
    from ...modals.mediator import MediatorProfile
    from ...utils.utils import get_hashed_password

    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    new_user = User(
        name=name,
        username=username,
        email=email,
        phone=phone,
        password_hash=get_hashed_password(password),
        role="mediator",
        is_active=True,
    )
    db.add(new_user)
    db.flush()

    chars = string.ascii_uppercase + string.digits
    referral_code = "HP-" + "".join(secrets.choice(chars) for _ in range(8))
    while db.query(MediatorProfile).filter(MediatorProfile.referral_code == referral_code).first():
        referral_code = "HP-" + "".join(secrets.choice(chars) for _ in range(8))

    now = datetime.datetime.now(timezone.utc)
    profile = MediatorProfile(
        user_id=new_user.id,
        mediator_type=mediator_type,
        verification_status="verified",
        verified_at=now,
        verified_by=_admin.id,
        referral_code=referral_code,
    )
    db.add(profile)
    db.commit()
    db.refresh(new_user)
    db.refresh(profile)

    return {
        "detail": f"Mediator '{name}' created and pre-verified",
        "user_id": new_user.id,
        "username": new_user.username,
        "referral_code": profile.referral_code,
        "verification_status": profile.verification_status,
    }


@router.get("/mediators")
def admin_list_mediators(
    status: str = Query(default=None, description="pending, verified, rejected"),
    mediator_type: str = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin lists all mediators with filters."""
    from ...modals.mediator import MediatorProfile, MediatorReliabilityScore

    q = db.query(MediatorProfile)
    if status:
        q = q.filter(MediatorProfile.verification_status == status)
    if mediator_type:
        q = q.filter(MediatorProfile.mediator_type == mediator_type)

    total = q.count()
    profiles = q.order_by(MediatorProfile.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for p in profiles:
        user = db.query(User).filter(User.id == p.user_id).first()
        score = db.query(MediatorReliabilityScore).filter(
            MediatorReliabilityScore.mediator_id == p.user_id,
        ).first()

        result.append({
            "id": p.id,
            "user_id": p.user_id,
            "name": user.name if user else None,
            "phone": user.phone if user else None,
            "email": user.email if user else None,
            "mediator_type": p.mediator_type,
            "verification_status": p.verification_status,
            "badge_issued": p.badge_issued,
            "wallet_balance": float(p.wallet_balance),
            "total_bookings": p.total_bookings,
            "total_earnings": float(p.total_earnings),
            "acquired_guests_count": p.acquired_guests_count,
            "referral_code": p.referral_code,
            "reliability_score": score.total_score if score else None,
            "score_tier": score.score_tier if score else None,
            "is_suspended": score.is_suspended if score else False,
            "created_at": p.created_at,
        })

    return {"total": total, "mediators": result}


@router.post("/mediators/{user_id}/verify")
def verify_mediator(
    user_id: int,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin approves a mediator's KYC."""
    from ...modals.mediator import MediatorProfile

    profile = db.query(MediatorProfile).filter(MediatorProfile.user_id == user_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Mediator profile not found")

    profile.verification_status = "verified"
    profile.verified_at = datetime.datetime.now(timezone.utc)
    profile.verified_by = _admin.id
    db.commit()

    return {"detail": f"Mediator {user_id} verified"}


@router.post("/mediators/{user_id}/reject")
def reject_mediator(
    user_id: int,
    reason: str = Query(..., min_length=1),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin rejects a mediator with reason."""
    from ...modals.mediator import MediatorProfile

    profile = db.query(MediatorProfile).filter(MediatorProfile.user_id == user_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Mediator profile not found")

    profile.verification_status = "rejected"
    profile.verification_note = reason
    db.commit()

    return {"detail": f"Mediator {user_id} rejected", "reason": reason}


@router.post("/mediators/{user_id}/suspend")
def suspend_mediator(
    user_id: int,
    days: int = Query(default=7, ge=1, le=90),
    reason: str = Query(default="Manual admin suspension"),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin manually suspends a mediator."""
    from ...modals.mediator import MediatorReliabilityScore, MediatorPenalty

    now = datetime.datetime.now(timezone.utc)
    suspended_until = now + datetime.timedelta(days=days)

    score = db.query(MediatorReliabilityScore).filter(
        MediatorReliabilityScore.mediator_id == user_id,
    ).first()
    if score:
        score.is_suspended = True
        score.suspended_until = suspended_until

    penalty = MediatorPenalty(
        mediator_id=user_id,
        penalty_type="suspension",
        reason=f"{reason} ({days} days)",
        expires_at=suspended_until,
    )
    db.add(penalty)
    db.commit()

    return {"detail": f"Mediator {user_id} suspended for {days} days"}


@router.post("/mediators/{user_id}/unsuspend")
def unsuspend_mediator(
    user_id: int,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin lifts a mediator suspension."""
    from ...modals.mediator import MediatorReliabilityScore, MediatorPenalty

    score = db.query(MediatorReliabilityScore).filter(
        MediatorReliabilityScore.mediator_id == user_id,
    ).first()
    if score:
        score.is_suspended = False
        score.suspended_until = None

    db.query(MediatorPenalty).filter(
        MediatorPenalty.mediator_id == user_id,
        MediatorPenalty.penalty_type == "suspension",
        MediatorPenalty.is_active == True,
    ).update({"is_active": False}, synchronize_session="fetch")

    db.commit()
    return {"detail": f"Mediator {user_id} unsuspended"}


@router.get("/mediators/{user_id}/stats")
def mediator_stats(
    user_id: int,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Detailed mediator stats for admin."""
    from ...modals.mediator import MediatorProfile, MediatorReliabilityScore
    from ...modals.mediator_commission import MediatorCommission, GuestAcquisition

    profile = db.query(MediatorProfile).filter(MediatorProfile.user_id == user_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Mediator profile not found")

    score = db.query(MediatorReliabilityScore).filter(
        MediatorReliabilityScore.mediator_id == user_id,
    ).first()

    total_commission = db.query(func.sum(MediatorCommission.commission_amount)).filter(
        MediatorCommission.mediator_id == user_id,
        MediatorCommission.status.in_(["pending", "approved", "paid"]),
    ).scalar() or Decimal("0")

    paid_commission = db.query(func.sum(MediatorCommission.commission_amount)).filter(
        MediatorCommission.mediator_id == user_id,
        MediatorCommission.status == "paid",
    ).scalar() or Decimal("0")

    acquired_guests = db.query(func.count(GuestAcquisition.id)).filter(
        GuestAcquisition.mediator_id == user_id,
    ).scalar() or 0

    total_bookings = db.query(func.count(Booking.id)).filter(
        Booking.mediator_id == user_id,
    ).scalar() or 0

    return {
        "user_id": user_id,
        "mediator_type": profile.mediator_type,
        "verification_status": profile.verification_status,
        "wallet_balance": float(profile.wallet_balance),
        "total_bookings": total_bookings,
        "commission": {
            "total_earned": float(total_commission),
            "total_paid": float(paid_commission),
            "pending": float(total_commission - paid_commission),
        },
        "acquired_guests": acquired_guests,
        "reliability": {
            "total_score": score.total_score if score else None,
            "tier": score.score_tier if score else None,
            "completion_rate": score.completion_rate if score else None,
            "guest_satisfaction": score.guest_satisfaction if score else None,
            "response_speed": score.response_speed if score else None,
            "accuracy": score.accuracy if score else None,
            "is_suspended": score.is_suspended if score else False,
        } if score else None,
    }


@router.post("/mediators/{user_id}/credit-wallet")
def credit_mediator_wallet(
    user_id: int,
    amount: float = Query(..., gt=0, description="Amount to credit in ₹"),
    description: str = Query(default="Admin credit", description="Reason for credit"),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin directly credits money to a mediator's wallet."""
    from ...modals.mediator import MediatorProfile, MediatorWalletTransaction

    profile = db.query(MediatorProfile).filter(MediatorProfile.user_id == user_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Mediator profile not found")

    profile.wallet_balance += Decimal(str(amount))
    new_balance = profile.wallet_balance

    tx = MediatorWalletTransaction(
        mediator_id=user_id,
        type="credit",
        amount=Decimal(str(amount)),
        balance_after=new_balance,
        reference=f"ADMIN-{_admin.id}",
        description=description,
    )
    db.add(tx)
    db.commit()

    # Send FCM notification
    from ...services.notifications import send_push_to_user
    try:
        send_push_to_user(
            user_id=user_id,
            db=db,
            title="Payment Credited!",
            body=f"₹{amount:.0f} has been added to your wallet. New balance: ₹{float(new_balance):.0f}",
            data={"type": "earnings_credited", "amount": str(amount)},
        )
    except Exception:
        pass  # Don't fail the credit if notification fails

    return {
        "detail": f"₹{amount:.0f} credited to mediator wallet",
        "new_balance": float(new_balance),
    }


@router.post("/owners/{user_id}/credit-earnings")
def credit_owner_earnings(
    user_id: int,
    amount: float = Query(..., gt=0, description="Amount to credit in ₹"),
    description: str = Query(default="Admin credit", description="Reason for credit"),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin directly credits earnings to a property owner."""
    from ...modals.booking import Payout

    user = db.query(User).filter(User.id == user_id, User.role == "owner").first()
    if not user:
        raise HTTPException(status_code=404, detail="Owner not found")

    payout = Payout(
        owner_id=user_id,
        booking_id=None,
        gross_amount=Decimal(str(amount)),
        commission_amount=Decimal("0"),
        net_amount=Decimal(str(amount)),
        status="processed",
    )
    db.add(payout)
    db.commit()

    # Send FCM notification
    from ...services.notifications import send_push_to_user
    try:
        send_push_to_user(
            user_id=user_id,
            db=db,
            title="Payment Credited!",
            body=f"₹{amount:.0f} has been credited to your account.",
            data={"type": "earnings_credited", "amount": str(amount)},
        )
    except Exception:
        pass

    return {"detail": f"₹{amount:.0f} credited to owner"}


@router.get("/matches")
def admin_mediator_matches(
    date_from: str = Query(default=None, description="Filter from date (YYYY-MM-DD)"),
    date_to: str = Query(default=None, description="Filter to date (YYYY-MM-DD)"),
    mediator_name: str = Query(default=None, description="Filter by mediator name (partial match)"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """
    Admin views all mediator-initiated pings that were accepted.
    Supports date range and mediator name filters.
    Returns full details: property, mediator, guest, owner — with phone numbers.
    """
    base_q = (
        db.query(PingSession)
        .filter(
            PingSession.mediator_id.isnot(None),
            PingSession.status == "accepted",
        )
    )

    # Date filters
    if date_from:
        try:
            from_dt = datetime.datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            base_q = base_q.filter(PingSession.responded_at >= from_dt)
        except ValueError:
            pass
    if date_to:
        try:
            to_dt = datetime.datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc) + datetime.timedelta(days=1)
            base_q = base_q.filter(PingSession.responded_at < to_dt)
        except ValueError:
            pass

    # Mediator name filter (join with User)
    if mediator_name:
        mediator_ids = [
            u.id for u in db.query(User).filter(
                User.role == "mediator",
                User.name.ilike(f"%{mediator_name}%")
            ).all()
        ]
        if mediator_ids:
            base_q = base_q.filter(PingSession.mediator_id.in_(mediator_ids))
        else:
            return {"total": 0, "matches": [], "has_more": False}

    total = base_q.count()

    pings = (
        base_q
        .order_by(PingSession.responded_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    result = []
    from ...services.ping import effective_guest_name_phone_for_mediator_ping

    for p in pings:
        prop = db.query(Property).filter(Property.id == p.property_id).first()
        guest = db.query(User).filter(User.id == p.guest_id).first()
        mediator = db.query(User).filter(User.id == p.mediator_id).first()
        owner = db.query(User).filter(User.id == p.owner_id).first()

        g_name, g_phone = effective_guest_name_phone_for_mediator_ping(p, guest)

        result.append({
            "id": p.id,
            "session_id": p.session_id,
            "property_id": p.property_id,
            "property_name": prop.name if prop else None,
            "property_city": prop.city if prop else None,
            "owner_id": p.owner_id,
            "owner_name": owner.name if owner else None,
            "owner_phone": owner.phone if owner else None,
            "mediator_id": p.mediator_id,
            "mediator_name": mediator.name if mediator else None,
            "mediator_phone": mediator.phone if mediator else None,
            "guest_id": p.guest_id,
            "guest_name": g_name,
            "guest_phone": g_phone,
            "check_in": str(p.check_in),
            "check_out": str(p.check_out),
            "guests_count": p.guests_count,
            "ping_type": p.ping_type,
            "response_time_seconds": p.owner_response_time,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "responded_at": p.responded_at.isoformat() if p.responded_at else None,
        })

    return {"total": total, "matches": result, "has_more": (skip + limit) < total}


@router.get("/mediators/commission-report")
def mediator_commission_report(
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Aggregate mediator commission report."""
    from ...modals.mediator_commission import MediatorCommission

    total_commissions = db.query(func.sum(MediatorCommission.commission_amount)).filter(
        MediatorCommission.status.in_(["pending", "approved", "paid"]),
    ).scalar() or Decimal("0")

    pending = db.query(func.sum(MediatorCommission.commission_amount)).filter(
        MediatorCommission.status == "pending",
    ).scalar() or Decimal("0")

    paid = db.query(func.sum(MediatorCommission.commission_amount)).filter(
        MediatorCommission.status == "paid",
    ).scalar() or Decimal("0")

    by_type = {}
    for ctype in ["booking", "residual", "bonus", "referral"]:
        amt = db.query(func.sum(MediatorCommission.commission_amount)).filter(
            MediatorCommission.commission_type == ctype,
        ).scalar() or Decimal("0")
        by_type[ctype] = float(amt)

    active_mediators = db.query(func.count(func.distinct(MediatorCommission.mediator_id))).filter(
        MediatorCommission.status.in_(["pending", "approved", "paid"]),
    ).scalar() or 0

    return {
        "total_commissions": float(total_commissions),
        "pending": float(pending),
        "paid": float(paid),
        "by_type": by_type,
        "active_mediators": active_mediators,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Analytics — read-only aggregations for the admin SaaS dashboard.
# All endpoints are admin-gated, accept optional date_from / date_to (ISO date),
# and are pure aggregation: no model or response-shape changes elsewhere.
# ══════════════════════════════════════════════════════════════════════════════


def _parse_date_range(
    date_from: str | None,
    date_to: str | None,
    default_days: int = 30,
) -> tuple[datetime.datetime, datetime.datetime]:
    """Parse YYYY-MM-DD strings into UTC datetimes covering the inclusive range.
    Defaults to the last `default_days` days when nothing is provided."""
    today = datetime.date.today()
    df = (
        datetime.date.fromisoformat(date_from)
        if date_from
        else today - datetime.timedelta(days=default_days - 1)
    )
    dt = datetime.date.fromisoformat(date_to) if date_to else today
    if dt < df:
        df, dt = dt, df
    start = datetime.datetime.combine(df, datetime.time.min)
    end = datetime.datetime.combine(dt + datetime.timedelta(days=1), datetime.time.min)
    return start, end


def _ping_status_counts(db: Session, start, end) -> dict:
    """Single GROUP BY query for status counts in [start, end)."""
    rows = (
        db.query(PingSession.status, func.count(PingSession.id))
        .filter(PingSession.created_at >= start, PingSession.created_at < end)
        .group_by(PingSession.status)
        .all()
    )
    return {status or "unknown": int(count) for status, count in rows}


@router.get("/analytics/overview")
def analytics_overview(
    date_from: str | None = Query(None, description="ISO date YYYY-MM-DD"),
    date_to: str | None = Query(None, description="ISO date YYYY-MM-DD"),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """KPI cards: ping counts, acceptance rate, response time, bookings, revenue,
    plus the same metrics for the prior period of equal length for delta deltas."""
    try:
        start, end = _parse_date_range(date_from, date_to)
    except ValueError:
        raise HTTPException(status_code=422, detail="Bad date format; use YYYY-MM-DD")

    span = end - start
    prev_start = start - span
    prev_end = start

    def metrics(s, e):
        counts = _ping_status_counts(db, s, e)
        total = sum(counts.values())
        accepted = counts.get("accepted", 0)
        rejected = counts.get("rejected", 0)
        expired = counts.get("expired", 0)
        pending = counts.get("pending", 0)
        responded = accepted + rejected
        avg_response = (
            db.query(func.avg(PingSession.owner_response_time))
            .filter(
                PingSession.created_at >= s,
                PingSession.created_at < e,
                PingSession.owner_response_time.isnot(None),
            )
            .scalar()
        )
        bookings = (
            db.query(func.count(Booking.id))
            .filter(Booking.created_at >= s, Booking.created_at < e)
            .scalar()
        ) or 0
        revenue = (
            db.query(func.coalesce(func.sum(Booking.total_amount), 0))
            .filter(
                Booking.created_at >= s,
                Booking.created_at < e,
                Booking.payment_status == "captured",
            )
            .scalar()
        ) or 0
        return {
            "total_pings": total,
            "accepted": accepted,
            "rejected": rejected,
            "expired": expired,
            "pending": pending,
            "missed": rejected + expired,  # what mediators/admins call "missed"
            "acceptance_rate": round((accepted / responded) * 100, 1) if responded else 0.0,
            "avg_response_seconds": round(float(avg_response), 1) if avg_response else None,
            "total_bookings": int(bookings),
            "total_revenue": float(revenue),
        }

    current = metrics(start, end)
    previous = metrics(prev_start, prev_end)

    return {
        "range": {"from": start.date().isoformat(), "to": (end - datetime.timedelta(days=1)).date().isoformat()},
        "current": current,
        "previous": previous,
    }


@router.get("/analytics/timeseries")
def analytics_timeseries(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    granularity: str = Query("day", pattern="^(day|week)$"),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Per-day (or per-week) ping totals split by status, for line/area charts."""
    try:
        start, end = _parse_date_range(date_from, date_to)
    except ValueError:
        raise HTTPException(status_code=422, detail="Bad date format; use YYYY-MM-DD")

    bucket = func.date_trunc(granularity, PingSession.created_at).label("bucket")
    rows = (
        db.query(bucket, PingSession.status, func.count(PingSession.id))
        .filter(PingSession.created_at >= start, PingSession.created_at < end)
        .group_by(bucket, PingSession.status)
        .order_by(bucket)
        .all()
    )

    series: dict[str, dict[str, int]] = {}
    for b, status, count in rows:
        key = b.date().isoformat() if hasattr(b, "date") else str(b)
        node = series.setdefault(key, {"date": key, "accepted": 0, "rejected": 0, "expired": 0, "pending": 0, "total": 0})
        if status in node:
            node[status] = int(count)
        node["total"] += int(count)

    # Fill empty buckets so the chart x-axis is continuous
    points: list[dict] = []
    cur = start
    step = datetime.timedelta(days=7 if granularity == "week" else 1)
    while cur < end:
        # Align week start to Monday for week granularity (date_trunc('week', …) → Monday in Postgres)
        if granularity == "week":
            week_start = cur - datetime.timedelta(days=cur.weekday())
            key = week_start.date().isoformat()
        else:
            key = cur.date().isoformat()
        if key not in series:
            series[key] = {"date": key, "accepted": 0, "rejected": 0, "expired": 0, "pending": 0, "total": 0}
        cur += step

    points = sorted(series.values(), key=lambda x: x["date"])
    return {"granularity": granularity, "points": points}


@router.get("/analytics/top-properties")
def analytics_top_properties(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    sort_by: str = Query("accepted", pattern="^(accepted|acceptance_rate|total_pings)$"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Top properties by acceptance count, acceptance rate, or volume."""
    try:
        start, end = _parse_date_range(date_from, date_to)
    except ValueError:
        raise HTTPException(status_code=422, detail="Bad date format; use YYYY-MM-DD")

    accepted_col = func.sum(case((PingSession.status == "accepted", 1), else_=0)).label("accepted")
    rejected_col = func.sum(case((PingSession.status == "rejected", 1), else_=0)).label("rejected")
    expired_col = func.sum(case((PingSession.status == "expired", 1), else_=0)).label("expired")
    total_col = func.count(PingSession.id).label("total")
    avg_response_col = func.avg(PingSession.owner_response_time).label("avg_response")

    rows = (
        db.query(
            Property.id,
            Property.name,
            Property.city,
            User.name.label("owner_name"),
            total_col,
            accepted_col,
            rejected_col,
            expired_col,
            avg_response_col,
        )
        .join(PingSession, PingSession.property_id == Property.id)
        .outerjoin(User, User.id == Property.owner_id)
        .filter(PingSession.created_at >= start, PingSession.created_at < end)
        .group_by(Property.id, Property.name, Property.city, User.name)
        .all()
    )

    items = []
    for r in rows:
        total = int(r.total or 0)
        accepted = int(r.accepted or 0)
        rejected = int(r.rejected or 0)
        expired = int(r.expired or 0)
        responded = accepted + rejected
        items.append({
            "property_id": r.id,
            "property_name": r.name,
            "city": r.city or "",
            "owner_name": r.owner_name or "—",
            "total_pings": total,
            "accepted": accepted,
            "rejected": rejected,
            "expired": expired,
            "missed": rejected + expired,
            "acceptance_rate": round((accepted / responded) * 100, 1) if responded else 0.0,
            "avg_response_seconds": round(float(r.avg_response), 1) if r.avg_response else None,
        })

    if sort_by == "acceptance_rate":
        items.sort(key=lambda x: (x["acceptance_rate"], x["accepted"]), reverse=True)
    elif sort_by == "total_pings":
        items.sort(key=lambda x: x["total_pings"], reverse=True)
    else:  # "accepted"
        items.sort(key=lambda x: x["accepted"], reverse=True)

    return {"items": items[:limit]}


@router.get("/analytics/missed-pings")
def analytics_missed_pings(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Properties with the most missed (rejected + expired) pings — 'who's leaking demand'."""
    try:
        start, end = _parse_date_range(date_from, date_to)
    except ValueError:
        raise HTTPException(status_code=422, detail="Bad date format; use YYYY-MM-DD")

    rejected_col = func.sum(case((PingSession.status == "rejected", 1), else_=0)).label("rejected")
    expired_col = func.sum(case((PingSession.status == "expired", 1), else_=0)).label("expired")
    accepted_col = func.sum(case((PingSession.status == "accepted", 1), else_=0)).label("accepted")
    missed_col = func.sum(
        case((PingSession.status.in_(("rejected", "expired")), 1), else_=0)
    ).label("missed")
    total_col = func.count(PingSession.id).label("total")

    rows = (
        db.query(
            Property.id,
            Property.name,
            Property.city,
            User.name.label("owner_name"),
            User.phone.label("owner_phone"),
            total_col,
            accepted_col,
            rejected_col,
            expired_col,
            missed_col,
        )
        .join(PingSession, PingSession.property_id == Property.id)
        .outerjoin(User, User.id == Property.owner_id)
        .filter(PingSession.created_at >= start, PingSession.created_at < end)
        .group_by(Property.id, Property.name, Property.city, User.name, User.phone)
        .having(missed_col > 0)
        .order_by(missed_col.desc())
        .limit(limit)
        .all()
    )

    items = []
    for r in rows:
        total = int(r.total or 0)
        accepted = int(r.accepted or 0)
        rejected = int(r.rejected or 0)
        expired = int(r.expired or 0)
        missed = int(r.missed or 0)
        items.append({
            "property_id": r.id,
            "property_name": r.name,
            "city": r.city or "",
            "owner_name": r.owner_name or "—",
            "owner_phone": r.owner_phone or "",
            "total_pings": total,
            "accepted": accepted,
            "rejected": rejected,
            "expired": expired,
            "missed": missed,
            "miss_rate": round((missed / total) * 100, 1) if total else 0.0,
        })
    return {"items": items}


@router.get("/analytics/response-time-histogram")
def analytics_response_time_histogram(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """How fast owners respond, bucketed for a histogram chart."""
    try:
        start, end = _parse_date_range(date_from, date_to)
    except ValueError:
        raise HTTPException(status_code=422, detail="Bad date format; use YYYY-MM-DD")

    # Bucket boundaries (seconds): 0-5, 5-10, 10-30, 30-60, 60+
    rt = PingSession.owner_response_time
    bucket_expr = case(
        (rt < 5, "0-5s"),
        (rt < 10, "5-10s"),
        (rt < 30, "10-30s"),
        (rt < 60, "30-60s"),
        else_="60s+",
    ).label("bucket")

    rows = (
        db.query(bucket_expr, func.count(PingSession.id))
        .filter(
            PingSession.created_at >= start,
            PingSession.created_at < end,
            rt.isnot(None),
        )
        .group_by(bucket_expr)
        .all()
    )
    counts = {b: int(c) for b, c in rows}
    order = ["0-5s", "5-10s", "10-30s", "30-60s", "60s+"]
    return {"buckets": [{"bucket": b, "count": counts.get(b, 0)} for b in order]}
