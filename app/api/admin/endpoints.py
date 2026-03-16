# HillPing — Admin Dashboard endpoints

import datetime
from datetime import timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

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
from ...services.platform_config import get_all_config, set_config, reset_config, DEFAULTS

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

    return {
        "properties": {
            "total": total_properties,
            "online": online_properties,
        },
        "users": {
            "owners": total_owners,
            "guests": total_guests,
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
        min_price = min((float(r.price_weekday) for r in rooms), default=None)
        total_capacity = sum(r.capacity for r in rooms)

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
            "booking_count": booking_count,
            "rooms": [
                {
                    "id": r.id,
                    "name": r.name,
                    "room_type": r.room_type,
                    "capacity": r.capacity,
                    "price_weekday": float(r.price_weekday),
                    "price_weekend": float(r.price_weekend),
                    "is_available": r.is_available,
                }
                for r in rooms
            ],
        })

    return {
        "total": total,
        "properties": result,
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
    role: str = Query(..., pattern=r'^(guest|owner|admin)$'),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin changes a user's role."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = role
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


# ── Booking overview ──────────────────────────────────────────────────────────

@router.get("/bookings")
def admin_list_bookings(
    status: str = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin lists all bookings."""
    q = db.query(Booking)
    if status:
        q = q.filter(Booking.status == status)
    total = q.count()
    bookings = q.order_by(Booking.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "bookings": [
            {
                "id": b.id,
                "booking_ref": b.booking_ref,
                "property_id": b.property_id,
                "guest_id": b.guest_id,
                "owner_id": b.owner_id,
                "check_in": str(b.check_in),
                "check_out": str(b.check_out),
                "total_amount": float(b.total_amount),
                "status": b.status,
                "payment_status": b.payment_status,
                "created_at": b.created_at,
            }
            for b in bookings
        ],
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
    value: str = Query(...),
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """
    Admin updates a single platform config key.

    Configurable keys include:
    - weight_acceptance, weight_response_time, weight_cancellation, weight_status_accuracy
    - response_time_max_seconds (the "worst" response time that scores 0)
    - instant_confirm_threshold
    - missed_pings_warning, rejections_rank_drop, cancellations_suspension, suspension_days
    - low_score_threshold, low_score_delist_weeks
    - ping_ttl_seconds, commission_percentage, min_booking_amount
    """
    if key not in DEFAULTS:
        raise HTTPException(status_code=400, detail=f"Unknown config key: {key}. Valid keys: {list(DEFAULTS.keys())}")

    # Validate numeric
    try:
        float(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Value must be numeric")

    record = set_config(key, value, db)
    return {
        "key": key,
        "value": value,
        "detail": f"Config '{key}' updated to {value}",
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
