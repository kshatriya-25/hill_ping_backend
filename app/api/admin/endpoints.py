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
    role: str = Query(..., pattern=r'^(guest|owner|mediator|admin)$'),
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
    for p in pings:
        prop = db.query(Property).filter(Property.id == p.property_id).first()
        guest = db.query(User).filter(User.id == p.guest_id).first()
        mediator = db.query(User).filter(User.id == p.mediator_id).first()
        owner = db.query(User).filter(User.id == p.owner_id).first()

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
            "guest_name": guest.name if guest else None,
            "guest_phone": guest.phone if guest else None,
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
