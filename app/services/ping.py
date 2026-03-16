# HillPing — Ping Session Service
#
# The 30-second availability confirmation flow:
# 1. Guest clicks "Check Availability"
# 2. Backend creates PingSession in Postgres + Redis (30s TTL)
# 3. WebSocket notification sent to owner (FCM fallback if offline)
# 4. Owner accepts/rejects within 30s
# 5. On accept → booking confirmed, payment captured
# 6. On reject/timeout → guest notified, payment released

import datetime
import logging
import uuid
from datetime import timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy import func

from ..core.config import settings
from ..database.redis import store_ping_session, get_ping_session, delete_ping_session, get_ping_ttl
from ..modals.ping import PingSession
from ..modals.property import Property, Room, DateBlock
from ..modals.reliability import OwnerReliabilityScore
from ..modals.masters import User
from ..services.reliability import (
    calculate_reliability_score,
    check_and_apply_penalties,
    update_instant_confirm_eligibility,
)

logger = logging.getLogger(__name__)


class PingError(Exception):
    """Raised when ping creation or response fails."""
    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code


def create_ping_session(
    guest_id: int,
    property_id: int,
    room_id: int | None,
    check_in: datetime.date,
    check_out: datetime.date,
    guests_count: int,
    db: Session,
) -> PingSession:
    """
    Create a new ping session:
    1. Validate property is ONLINE and owner is not suspended
    2. Check for date blocks
    3. Check if instant-confirm eligible (skip ping, auto-confirm)
    4. Create PingSession in DB and Redis
    """
    # ── Validate property ─────────────────────────────────────────────────
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise PingError("Property not found", 404)

    if prop.status == "offline":
        raise PingError("This property is currently not accepting bookings")
    if prop.status == "full":
        raise PingError("This property is fully booked")

    owner = db.query(User).filter(User.id == prop.owner_id).first()
    if not owner or not owner.is_active:
        raise PingError("Property owner is unavailable")

    # Check if owner is suspended
    score = db.query(OwnerReliabilityScore).filter(
        OwnerReliabilityScore.owner_id == prop.owner_id
    ).first()
    if score and score.is_suspended:
        raise PingError("This property is temporarily unavailable")

    # ── Validate room if specified ────────────────────────────────────────
    if room_id:
        room = db.query(Room).filter(
            Room.id == room_id, Room.property_id == property_id, Room.is_available == True
        ).first()
        if not room:
            raise PingError("Room not found or unavailable", 404)

    # ── Check date blocks ─────────────────────────────────────────────────
    blocked = db.query(DateBlock).filter(
        DateBlock.property_id == property_id,
        DateBlock.block_date >= check_in,
        DateBlock.block_date < check_out,
    )
    if room_id:
        blocked = blocked.filter((DateBlock.room_id == room_id) | (DateBlock.room_id == None))
    if blocked.first():
        raise PingError("Property is blocked for the selected dates")

    # ── Check for existing active ping from this guest for this property ──
    existing = db.query(PingSession).filter(
        PingSession.guest_id == guest_id,
        PingSession.property_id == property_id,
        PingSession.status == "pending",
    ).first()
    if existing:
        raise PingError("You already have a pending availability check for this property")

    # ── Create ping session ───────────────────────────────────────────────
    session_id = uuid.uuid4().hex
    now = datetime.datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.PING_TTL_SECONDS)

    ping = PingSession(
        session_id=session_id,
        property_id=property_id,
        room_id=room_id,
        guest_id=guest_id,
        owner_id=prop.owner_id,
        check_in=check_in,
        check_out=check_out,
        guests_count=guests_count,
        status="pending",
        expires_at=expires_at,
    )
    db.add(ping)
    db.commit()
    db.refresh(ping)

    # ── Store in Redis for TTL tracking ───────────────────────────────────
    redis_data = {
        "ping_id": ping.id,
        "session_id": session_id,
        "property_id": property_id,
        "room_id": room_id,
        "guest_id": guest_id,
        "owner_id": prop.owner_id,
        "check_in": str(check_in),
        "check_out": str(check_out),
        "guests_count": guests_count,
        "property_name": prop.name,
    }
    store_ping_session(session_id, redis_data)

    logger.info(
        "Ping session %s created: guest=%d → property=%d (owner=%d), TTL=%ds",
        session_id, guest_id, property_id, prop.owner_id, settings.PING_TTL_SECONDS,
    )

    return ping


def handle_ping_response(
    session_id: str,
    owner_id: int,
    action: str,  # "accept" or "reject"
    db: Session,
) -> PingSession:
    """
    Process owner's response to a ping.
    1. Validate session exists and is still pending
    2. Check Redis TTL (not expired)
    3. Update DB record
    4. Clean up Redis
    5. Trigger reliability recalculation
    """
    ping = db.query(PingSession).filter(
        PingSession.session_id == session_id,
    ).first()

    if not ping:
        raise PingError("Ping session not found", 404)
    if ping.owner_id != owner_id:
        raise PingError("Not authorized to respond to this ping", 403)
    if ping.status != "pending":
        raise PingError(f"Ping already {ping.status}")

    # Check Redis — if key is gone, it's expired
    redis_data = get_ping_session(session_id)
    if redis_data is None:
        # TTL expired, mark as expired in DB
        ping.status = "expired"
        db.commit()
        raise PingError("Ping session has expired")

    now = datetime.datetime.now(timezone.utc)
    response_time = (now - ping.created_at.replace(tzinfo=timezone.utc)).total_seconds()

    ping.status = "accepted" if action == "accept" else "rejected"
    ping.responded_at = now
    ping.owner_response_time = round(response_time, 2)
    db.commit()

    # Clean up Redis
    delete_ping_session(session_id)

    # ── Recalculate reliability score ─────────────────────────────────────
    _recalculate_owner_score(owner_id, db)

    logger.info(
        "Ping %s %s by owner %d in %.1fs",
        session_id, action, owner_id, response_time,
    )

    return ping


def expire_ping_session_by_id(session_id: str, db: Session) -> PingSession | None:
    """
    Mark a ping session as expired (called when Redis TTL fires or on status check).
    """
    ping = db.query(PingSession).filter(
        PingSession.session_id == session_id,
        PingSession.status == "pending",
    ).first()

    if not ping:
        return None

    ping.status = "expired"
    ping.responded_at = datetime.datetime.now(timezone.utc)
    db.commit()

    # Count as missed ping for reliability
    _recalculate_owner_score(ping.owner_id, db)

    logger.info("Ping %s expired (owner %d did not respond)", session_id, ping.owner_id)
    return ping


def check_and_expire_pending(session_id: str, db: Session) -> str:
    """
    Check if a pending ping has expired (Redis key gone) and update DB accordingly.
    Returns the current status.
    """
    ping = db.query(PingSession).filter(PingSession.session_id == session_id).first()
    if not ping:
        return "not_found"

    if ping.status != "pending":
        return ping.status

    # Check Redis
    redis_data = get_ping_session(session_id)
    if redis_data is None:
        # Expired
        expire_ping_session_by_id(session_id, db)
        return "expired"

    return "pending"


def get_pending_pings_for_owner(owner_id: int, db: Session) -> list[PingSession]:
    """Get all pending pings for an owner."""
    return db.query(PingSession).filter(
        PingSession.owner_id == owner_id,
        PingSession.status == "pending",
    ).order_by(PingSession.created_at.desc()).all()


def check_instant_confirm(property_id: int, db: Session) -> bool:
    """Check if a property is eligible for instant confirm (bypass ping)."""
    prop = db.query(Property).filter(Property.id == property_id).first()
    return prop is not None and prop.is_instant_confirm


# ── Internal helpers ──────────────────────────────────────────────────────────

def _recalculate_owner_score(owner_id: int, db: Session) -> None:
    """Aggregate ping stats and recalculate reliability score."""
    from datetime import timedelta

    now = datetime.datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # Total lifetime ping stats
    total_pings = db.query(func.count(PingSession.id)).filter(
        PingSession.owner_id == owner_id,
    ).scalar() or 0

    accepted = db.query(func.count(PingSession.id)).filter(
        PingSession.owner_id == owner_id,
        PingSession.status == "accepted",
    ).scalar() or 0

    rejected = db.query(func.count(PingSession.id)).filter(
        PingSession.owner_id == owner_id,
        PingSession.status == "rejected",
    ).scalar() or 0

    expired = db.query(func.count(PingSession.id)).filter(
        PingSession.owner_id == owner_id,
        PingSession.status == "expired",
    ).scalar() or 0

    # Average response time (only for responded pings)
    avg_response = db.query(func.avg(PingSession.owner_response_time)).filter(
        PingSession.owner_id == owner_id,
        PingSession.owner_response_time != None,
    ).scalar() or 0.0

    # Weekly/monthly stats for penalties
    missed_this_week = db.query(func.count(PingSession.id)).filter(
        PingSession.owner_id == owner_id,
        PingSession.status == "expired",
        PingSession.created_at >= week_ago,
    ).scalar() or 0

    rejections_this_month = db.query(func.count(PingSession.id)).filter(
        PingSession.owner_id == owner_id,
        PingSession.status == "rejected",
        PingSession.created_at >= month_ago,
    ).scalar() or 0

    # Calculate score
    calculate_reliability_score(
        owner_id, db,
        total_pings=total_pings,
        accepted_pings=accepted,
        rejected_pings=rejected,
        expired_pings=expired,
        avg_response_seconds=float(avg_response),
        missed_while_online=expired,
        total_while_online=total_pings,
    )

    # Check penalties
    check_and_apply_penalties(
        owner_id, db,
        missed_pings_this_week=missed_this_week,
        rejections_this_month=rejections_this_month,
    )

    # Update instant confirm eligibility
    update_instant_confirm_eligibility(owner_id, db)
