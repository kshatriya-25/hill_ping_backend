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
    profile = db.query(MediatorProfile).filter(
        MediatorProfile.user_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Mediator profile not found")
    return profile


@router.patch("/profile", response_model=MediatorProfileResponse)
def update_profile(
    data: MediatorProfileUpdate,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Update mediator profile fields."""
    profile = db.query(MediatorProfile).filter(
        MediatorProfile.user_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Mediator profile not found")

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

    profile = db.query(MediatorProfile).filter(
        MediatorProfile.user_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Mediator profile not found")

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
    Uses Haversine approximation for distance calculation.
    """
    from ...modals.property import Property, Room
    from sqlalchemy import func, cast, Float, case, literal_column
    import math

    # Haversine distance approximation in SQL (returns km)
    # For small distances, this is accurate enough
    lat_rad = math.radians(latitude)
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

    # Filter by price range (join rooms)
    if min_price or max_price:
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

    return [
        {
            "id": prop.id,
            "name": prop.name,
            "property_type": prop.property_type,
            "distance_km": round(float(dist), 2),
            "latitude": prop.latitude,
            "longitude": prop.longitude,
            "status": prop.status,
            "is_instant_confirm": prop.is_instant_confirm,
            "address": prop.address,
        }
        for prop, dist in results
    ]


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

    # Notify all owners via WebSocket
    for ping in pings:
        background_tasks.add_task(
            ws_manager.send_to_user,
            ping.owner_id,
            {
                "type": "ping_received",
                "session_id": ping.session_id,
                "property_id": ping.property_id,
                "check_in": str(ping.check_in),
                "check_out": str(ping.check_out),
                "guests_count": ping.guests_count,
                "is_bulk": True,
                "ttl_seconds": int((ping.expires_at - ping.created_at).total_seconds()),
                "expires_at": ping.expires_at.isoformat(),
            },
        )

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
    profile = db.query(MediatorProfile).filter(
        MediatorProfile.user_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Mediator profile not found")

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

    profile = db.query(MediatorProfile).filter(
        MediatorProfile.user_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Mediator profile not found")

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
