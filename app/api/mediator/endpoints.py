# HillPing — Mediator endpoints (V2)

import secrets
import string
import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address

from ...core.config import settings
from ...database.session import getdb
from ...modals.masters import User
from ...modals.property import Property
from ...modals.mediator import MediatorProfile
from ...schemas.mediatorSchema import (
    MediatorRegister,
    MediatorProfileUpdate,
    MediatorProfileResponse,
    MediatorDashboard,
    BulkPingRequest,
)
from ...schemas.pingSchema import PingSessionResponse
from ...utils.utils import (
    get_current_user,
    get_hashed_password,
    create_access_token,
    create_refresh_token,
    require_role,
    validate_password_strength,
)
from ...services.ping import create_bulk_ping_sessions, get_bulk_ping_status, PingError

router = APIRouter(tags=["mediator"])
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)


def _generate_referral_code(length: int = 8) -> str:
    """Generate a unique alphanumeric referral code."""
    chars = string.ascii_uppercase + string.digits
    return "HP-" + "".join(secrets.choice(chars) for _ in range(length))


def _get_or_create_mediator_profile(db: Session, user_id: int) -> MediatorProfile:
    """
    Get mediator profile, auto-creating one if the user was assigned
    the mediator role via admin without going through /register.
    """
    profile = db.query(MediatorProfile).filter(
        MediatorProfile.user_id == user_id
    ).first()
    if profile:
        return profile

    referral_code = _generate_referral_code()
    while db.query(MediatorProfile).filter(MediatorProfile.referral_code == referral_code).first():
        referral_code = _generate_referral_code()

    profile = MediatorProfile(
        user_id=user_id,
        mediator_type="freelance_agent",
        verification_status="verified",
        referral_code=referral_code,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    logger.info("Auto-created mediator profile for user_id=%d", user_id)
    return profile


# ── Registration ──────────────────────────────────────────────────────────────

@router.post("/register")
@limiter.limit(settings.RATE_LIMIT_LOGIN)
def register_mediator(
    request: Request,
    data: MediatorRegister,
    db: Session = Depends(getdb),
):
    """
    Mediator self-registration.
    Creates User (role=mediator) + MediatorProfile (verification_status=pending).
    Account is inactive until admin approves.
    """
    validate_password_strength(data.password)

    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    # Create user
    new_user = User(
        name=data.name,
        username=data.username,
        email=data.email,
        phone=data.phone,
        password_hash=get_hashed_password(data.password),
        role="mediator",
        is_active=True,
    )
    db.add(new_user)
    db.flush()  # get new_user.id

    # Generate unique referral code
    referral_code = _generate_referral_code()
    while db.query(MediatorProfile).filter(MediatorProfile.referral_code == referral_code).first():
        referral_code = _generate_referral_code()

    # Resolve referrer
    referred_by = None
    if data.referral_code:
        referrer = db.query(MediatorProfile).filter(
            MediatorProfile.referral_code == data.referral_code
        ).first()
        if referrer:
            referred_by = referrer.id

    # Hash aadhaar if provided (we never store raw aadhaar)
    aadhaar_hash = None
    if data.aadhaar_doc_url:
        # The doc URL is stored; actual number would be hashed separately if collected
        pass

    profile = MediatorProfile(
        user_id=new_user.id,
        mediator_type=data.mediator_type,
        operating_zone=data.operating_zone,
        aadhaar_doc_url=data.aadhaar_doc_url,
        verification_status="pending",
        referral_code=referral_code,
        referred_by=referred_by,
    )
    db.add(profile)
    db.commit()
    db.refresh(new_user)
    db.refresh(profile)

    access_token = create_access_token(new_user.id, new_user.username, new_user.role)
    refresh_token = create_refresh_token(new_user.id, new_user.username, new_user.role, db=db)

    logger.info("Mediator registered: user_id=%d, type=%s", new_user.id, data.mediator_type)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": new_user.id,
            "username": new_user.username,
            "email": new_user.email,
            "name": new_user.name,
            "role": new_user.role,
        },
        "profile": {
            "id": profile.id,
            "verification_status": profile.verification_status,
            "referral_code": profile.referral_code,
            "mediator_type": profile.mediator_type,
        },
    }


# ── Profile ───────────────────────────────────────────────────────────────────

@router.get("/profile", response_model=MediatorProfileResponse)
def get_profile(
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Get the current mediator's profile."""
    profile = _get_or_create_mediator_profile(db, current_user.id)
    return profile


@router.patch("/profile", response_model=MediatorProfileResponse)
def update_profile(
    data: MediatorProfileUpdate,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Update mediator profile fields."""
    profile = _get_or_create_mediator_profile(db, current_user.id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=MediatorDashboard)
def get_dashboard(
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Get mediator dashboard stats."""
    from ...modals.booking import Booking
    from ...modals.mediator import MediatorReliabilityScore
    import datetime

    profile = _get_or_create_mediator_profile(db, current_user.id)

    today = datetime.date.today()
    month_start = today.replace(day=1)

    todays_bookings = db.query(Booking).filter(
        Booking.mediator_id == current_user.id,
        Booking.status.in_(["confirmed", "completed"]),
        Booking.created_at >= datetime.datetime.combine(today, datetime.time.min),
    ).count()

    reliability = db.query(MediatorReliabilityScore).filter(
        MediatorReliabilityScore.mediator_id == current_user.id
    ).first()

    return MediatorDashboard(
        todays_bookings=todays_bookings,
        pending_payouts=0,  # TODO: calculate from mediator_commissions
        this_month_earnings=0,  # TODO: calculate from mediator_commissions
        success_rate=0.0,  # TODO: calculate from ping conversions
        reliability_score=reliability.total_score if reliability else 100.0,
        wallet_balance=profile.wallet_balance,
    )


# ── Search (distance-sorted) ─────────────────────────────────────────────────

@router.get("/search")
def search_properties(
    latitude: float,
    longitude: float,
    max_distance_km: float = 5.0,
    min_price: int | None = None,
    max_price: int | None = None,
    guests: int = 1,
    room_type: str | None = None,
    instant_confirm_only: bool = False,
    limit: int = 20,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """
    Search properties sorted by distance from mediator's current GPS location.
    Returns rich data: photos, price, rating, commission estimate.
    """
    from ...modals.property import Property, Room, PropertyPhoto
    from ...modals.review import Review
    from ...services.platform_config import get_config
    from sqlalchemy import func
    import math

    # Haversine distance approximation in SQL (returns km)
    dlat = func.radians(Property.latitude - latitude)
    dlng = func.radians(Property.longitude - longitude)
    a = (
        func.sin(dlat / 2) * func.sin(dlat / 2)
        + func.cos(func.radians(latitude))
        * func.cos(func.radians(Property.latitude))
        * func.sin(dlng / 2) * func.sin(dlng / 2)
    )
    distance_km = 6371 * 2 * func.atan2(func.sqrt(a), func.sqrt(1 - a))

    query = db.query(
        Property,
        distance_km.label("distance_km"),
    ).filter(
        Property.status == "online",
        Property.latitude.isnot(None),
        Property.longitude.isnot(None),
    )

    if instant_confirm_only:
        query = query.filter(Property.is_instant_confirm == True)

    # Filter by distance
    query = query.having(distance_km <= max_distance_km)

    # Filter by price range (join rooms to check price)
    if min_price or max_price or guests > 1:
        query = query.join(Room, Room.property_id == Property.id)
        if min_price:
            query = query.filter(Room.price_weekday >= min_price)
        if max_price:
            query = query.filter(Room.price_weekday <= max_price)
        if guests > 1:
            query = query.filter(Room.capacity >= guests)

    query = query.group_by(Property.id)
    query = query.order_by(distance_km.asc())
    query = query.limit(limit)

    results = query.all()

    # Get commission tiers from platform config
    tier1_flat = float(get_config("mediator_commission_tier1_flat", db) or "50")
    tier2_rate = float(get_config("mediator_commission_tier2_rate", db) or "5")
    tier3_rate = float(get_config("mediator_commission_tier3_rate", db) or "6")
    tier4_rate = float(get_config("mediator_commission_tier4_rate", db) or "7")

    def estimate_commission(price):
        """Estimate mediator commission based on nightly price."""
        if price is None:
            return 0
        p = float(price)
        if p <= 1000:
            return tier1_flat
        elif p <= 3000:
            return round(p * tier2_rate / 100)
        elif p <= 10000:
            return round(p * tier3_rate / 100)
        else:
            return round(p * tier4_rate / 100)

    response = []
    for prop, dist in results:
        # Get rooms for price info
        rooms = db.query(Room).filter(Room.property_id == prop.id).all()
        price_min = min((r.price_weekday for r in rooms), default=None) if rooms else None
        rooms_count = len(rooms)

        # Get photos
        photos = db.query(PropertyPhoto).filter(
            PropertyPhoto.property_id == prop.id
        ).order_by(PropertyPhoto.display_order).all()
        photo_urls = [p.url for p in photos]

        # Get rating
        rating_result = db.query(func.avg(Review.rating_overall)).filter(Review.property_id == prop.id).scalar()

        # Get owner name
        owner = db.query(User).filter(User.id == prop.owner_id).first()

        # Commission estimate
        commission = estimate_commission(price_min)

        response.append({
            "id": prop.id,
            "name": prop.name,
            "city": prop.city or "",
            "state": prop.state,
            "property_type": prop.property_type,
            "status": prop.status,
            "is_verified": prop.is_verified,
            "is_instant_confirm": prop.is_instant_confirm,
            "cover_photo": prop.cover_photo,
            "photos": photo_urls,
            "price_min": float(price_min) if price_min else None,
            "rating_avg": round(float(rating_result), 1) if rating_result else None,
            "owner_name": owner.name if owner else None,
            "rooms_count": rooms_count,
            "latitude": prop.latitude,
            "longitude": prop.longitude,
            "distance_km": round(float(dist), 2),
            "commission_estimate": commission,
        })

    return response


# ── Bulk Ping ─────────────────────────────────────────────────────────────────

@router.post("/bulk-ping")
def bulk_ping(
    data: BulkPingRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """
    Ping up to 3 properties simultaneously.
    Unlike guest pings, mediator bulk pings collect ALL responses.
    """
    from datetime import date as date_type, timedelta
    from ...api.ws.connection_manager import ws_manager

    # Default dates: today → tomorrow
    today = date_type.today()
    try:
        check_in = date_type.fromisoformat(data.check_in) if data.check_in else today
        check_out = date_type.fromisoformat(data.check_out) if data.check_out else today + timedelta(days=1)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD")

    # Accept both guest_count and guests_count from frontend
    guests = data.guests_count or data.guest_count or 1

    try:
        pings = create_bulk_ping_sessions(
            mediator_id=current_user.id,
            property_ids=data.property_ids,
            check_in=check_in,
            check_out=check_out,
            guests_count=guests,
            guest_id=data.guest_id,
            db=db,
            ttl_seconds=data.ttl_seconds,
        )
    except PingError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    # Notify all owners via WebSocket + FCM push
    from ...services.notifications import send_ping_notification
    from ...database.session import SessionLocal
    for ping in pings:
        prop = db.query(Property).filter(Property.id == ping.property_id).first()
        ping_data = {
            "type": "ping_received",
            "session_id": ping.session_id,
            "property_id": ping.property_id,
            "property_name": prop.name if prop else "",
            "check_in": str(ping.check_in),
            "check_out": str(ping.check_out),
            "guests_count": ping.guests_count,
            "is_bulk": True,
            "ttl_seconds": int((ping.expires_at - ping.created_at).total_seconds()),
            "expires_at": ping.expires_at.isoformat(),
        }
        background_tasks.add_task(ws_manager.send_to_user, ping.owner_id, ping_data)
        # FCM push — use fresh DB session since request session closes after response
        def _send_fcm(owner_id=ping.owner_id, data=ping_data):
            fcm_db = SessionLocal()
            try:
                logger.info("FCM: Sending push to owner %d", owner_id)
                result = send_ping_notification(owner_id, data, fcm_db)
                logger.info("FCM: send_ping_notification returned %s", result)
            except Exception as e:
                logger.error("FCM push failed: %s", e, exc_info=True)
            finally:
                fcm_db.close()
        background_tasks.add_task(_send_fcm)

    group_id = pings[0].bulk_ping_group_id if pings else None

    return {
        "bulk_ping_group_id": group_id,
        "total_pinged": len(pings),
        "pings": [PingSessionResponse.model_validate(p).model_dump() for p in pings],
    }


@router.get("/bulk-ping/{group_id}/status")
def bulk_ping_status(
    group_id: str,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Get status of all pings in a bulk ping group."""
    pings = get_bulk_ping_status(group_id, db)
    if not pings:
        raise HTTPException(status_code=404, detail="Bulk ping group not found")

    # Verify mediator owns this group
    if pings[0].mediator_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    return {
        "bulk_ping_group_id": group_id,
        "pings": [PingSessionResponse.model_validate(p).model_dump() for p in pings],
        "summary": {
            "total": len(pings),
            "accepted": sum(1 for p in pings if p.status == "accepted"),
            "rejected": sum(1 for p in pings if p.status == "rejected"),
            "pending": sum(1 for p in pings if p.status == "pending"),
            "expired": sum(1 for p in pings if p.status == "expired"),
        },
    }


# ── Wallet ────────────────────────────────────────────────────────────────────

@router.get("/wallet/balance")
def wallet_balance(
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Get mediator wallet balance."""
    profile = _get_or_create_mediator_profile(db, current_user.id)

    return {
        "balance": float(profile.wallet_balance),
        "user_id": current_user.id,
    }


@router.get("/wallet/transactions")
def wallet_transactions(
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Get mediator wallet transaction history."""
    from ...modals.mediator import MediatorWalletTransaction

    txns = db.query(MediatorWalletTransaction).filter(
        MediatorWalletTransaction.mediator_id == current_user.id,
    ).order_by(MediatorWalletTransaction.created_at.desc()).limit(50).all()

    return [
        {
            "id": t.id,
            "type": t.type,
            "amount": float(t.amount),
            "balance_after": float(t.balance_after),
            "reference": t.reference,
            "description": t.description,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in txns
    ]


@router.post("/wallet/topup")
def wallet_topup(
    amount: float,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Top up mediator wallet (simplified — in production, integrate Razorpay)."""
    from decimal import Decimal
    from ...modals.mediator import MediatorWalletTransaction

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    profile = _get_or_create_mediator_profile(db, current_user.id)

    profile.wallet_balance += Decimal(str(amount))

    txn = MediatorWalletTransaction(
        mediator_id=current_user.id,
        type="topup",
        amount=Decimal(str(amount)),
        balance_after=profile.wallet_balance,
        description=f"Wallet top-up of ₹{amount}",
    )
    db.add(txn)
    db.commit()

    return {
        "detail": f"₹{amount} added to wallet",
        "balance": float(profile.wallet_balance),
    }
