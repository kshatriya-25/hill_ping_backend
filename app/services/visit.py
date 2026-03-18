# HillPing — Visit Request Service (V2)
#
# Room hold flow:
# 1. Mediator requests visit after ping acceptance
# 2. Room is HELD for 45 minutes (Redis TTL)
# 3. Mediator drives tourist to property
# 4. Tourist inspects → mediator taps Book or Pass
# 5. Hold released on pass/expiry/book

import datetime
import logging
import secrets
import string
from datetime import timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy import func

from ..core.config import settings
from ..database.redis import (
    store_visit_hold, get_visit_hold, delete_visit_hold,
    get_visit_hold_ttl, extend_visit_hold,
)
from ..modals.visit import VisitRequest
from ..modals.property import Property
from ..modals.masters import User

logger = logging.getLogger(__name__)

MAX_ACTIVE_HOLDS_PER_MEDIATOR = 2
HOLD_EXTENSION_SECONDS = 900  # 15 minutes


class VisitError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code


def _generate_visit_ref() -> str:
    chars = string.ascii_uppercase + string.digits
    return "V-" + "".join(secrets.choice(chars) for _ in range(6))


def create_visit_request(
    mediator_id: int,
    property_id: int,
    room_id: int | None,
    guest_id: int | None,
    guest_count: int,
    eta_minutes: int | None,
    ping_session_id: int | None,
    tour_session_id: int | None,
    tour_stop_order: int | None,
    db: Session,
) -> VisitRequest:
    """Create a visit request with a 45-minute room hold."""

    # Check active hold cap
    active_holds = db.query(func.count(VisitRequest.id)).filter(
        VisitRequest.mediator_id == mediator_id,
        VisitRequest.status.in_(["requested", "en_route", "arrived"]),
    ).scalar() or 0

    if active_holds >= MAX_ACTIVE_HOLDS_PER_MEDIATOR:
        raise VisitError(f"Maximum {MAX_ACTIVE_HOLDS_PER_MEDIATOR} active holds allowed")

    # Validate property
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise VisitError("Property not found", 404)

    # Check no existing active hold on this specific room for this property
    existing = db.query(VisitRequest).filter(
        VisitRequest.property_id == property_id,
        VisitRequest.status.in_(["requested", "en_route", "arrived"]),
    )
    if room_id:
        existing = existing.filter(VisitRequest.room_id == room_id)
    if existing.first():
        raise VisitError("This room already has an active visit in progress")

    visit_ref = _generate_visit_ref()
    # Ensure uniqueness
    while db.query(VisitRequest).filter(VisitRequest.visit_ref == visit_ref).first():
        visit_ref = _generate_visit_ref()

    now = datetime.datetime.now(timezone.utc)
    hold_expires_at = now + timedelta(seconds=settings.VISIT_HOLD_TTL_SECONDS)

    visit = VisitRequest(
        visit_ref=visit_ref,
        mediator_id=mediator_id,
        property_id=property_id,
        room_id=room_id,
        guest_id=guest_id,
        owner_id=prop.owner_id,
        ping_session_id=ping_session_id,
        tour_session_id=tour_session_id,
        tour_stop_order=tour_stop_order,
        guest_count=guest_count,
        eta_minutes=eta_minutes,
        status="requested",
        hold_expires_at=hold_expires_at,
    )
    db.add(visit)
    db.commit()
    db.refresh(visit)

    # Store hold in Redis
    redis_data = {
        "visit_id": visit.id,
        "visit_ref": visit_ref,
        "mediator_id": mediator_id,
        "property_id": property_id,
        "room_id": room_id,
        "owner_id": prop.owner_id,
        "guest_count": guest_count,
        "eta_minutes": eta_minutes,
    }
    store_visit_hold(visit_ref, redis_data)

    logger.info(
        "Visit request %s created: mediator=%d → property=%d, hold=%ds",
        visit_ref, mediator_id, property_id, settings.VISIT_HOLD_TTL_SECONDS,
    )

    return visit


def arrive_at_property(visit_ref: str, mediator_id: int, db: Session) -> VisitRequest:
    """Mark mediator as arrived at the property."""
    visit = _get_active_visit(visit_ref, mediator_id, db)

    if visit.status not in ("requested", "en_route"):
        raise VisitError(f"Cannot mark arrived — visit is {visit.status}")

    visit.status = "arrived"
    visit.arrived_at = datetime.datetime.now(timezone.utc)
    db.commit()
    db.refresh(visit)

    logger.info("Visit %s: mediator %d arrived at property %d", visit_ref, mediator_id, visit.property_id)
    return visit


def book_from_visit(visit_ref: str, mediator_id: int, db: Session) -> VisitRequest:
    """Tourist liked it — mark visit as booked and release hold."""
    visit = _get_active_visit(visit_ref, mediator_id, db)

    visit.status = "booked"
    visit.decided_at = datetime.datetime.now(timezone.utc)
    db.commit()

    # Release Redis hold
    delete_visit_hold(visit_ref)

    logger.info("Visit %s booked by mediator %d", visit_ref, mediator_id)
    return visit


def pass_visit(visit_ref: str, mediator_id: int, reason: str | None, db: Session) -> VisitRequest:
    """Tourist rejected — release hold, record reason."""
    visit = _get_active_visit(visit_ref, mediator_id, db)

    visit.status = "passed"
    visit.pass_reason = reason
    visit.decided_at = datetime.datetime.now(timezone.utc)
    db.commit()

    # Release Redis hold
    delete_visit_hold(visit_ref)

    logger.info("Visit %s passed by mediator %d (reason: %s)", visit_ref, mediator_id, reason)
    return visit


def extend_visit(visit_ref: str, mediator_id: int, db: Session) -> VisitRequest:
    """Extend hold by 15 minutes (once per visit)."""
    visit = _get_active_visit(visit_ref, mediator_id, db)

    if visit.hold_extended:
        raise VisitError("Hold can only be extended once")

    success = extend_visit_hold(visit_ref, HOLD_EXTENSION_SECONDS)
    if not success:
        raise VisitError("Hold has already expired")

    visit.hold_extended = True
    visit.hold_expires_at = visit.hold_expires_at + timedelta(seconds=HOLD_EXTENSION_SECONDS)
    db.commit()
    db.refresh(visit)

    logger.info("Visit %s hold extended by %ds", visit_ref, HOLD_EXTENSION_SECONDS)
    return visit


def expire_visit(visit_ref: str, db: Session) -> VisitRequest | None:
    """Called when Redis TTL expires or on status check."""
    visit = db.query(VisitRequest).filter(
        VisitRequest.visit_ref == visit_ref,
        VisitRequest.status.in_(["requested", "en_route", "arrived"]),
    ).first()

    if not visit:
        return None

    visit.status = "expired"
    visit.decided_at = datetime.datetime.now(timezone.utc)
    db.commit()

    logger.info("Visit %s expired", visit_ref)
    return visit


def release_hold_by_owner(visit_ref: str, owner_id: int, db: Session) -> VisitRequest:
    """Owner releases hold early (mediator no-show)."""
    visit = db.query(VisitRequest).filter(
        VisitRequest.visit_ref == visit_ref,
    ).first()

    if not visit:
        raise VisitError("Visit not found", 404)
    if visit.owner_id != owner_id:
        raise VisitError("Not authorized", 403)
    if visit.status not in ("requested", "en_route"):
        raise VisitError(f"Cannot release — visit is {visit.status}")

    visit.status = "owner_released"
    visit.decided_at = datetime.datetime.now(timezone.utc)
    db.commit()

    delete_visit_hold(visit_ref)

    logger.info("Visit %s released by owner %d", visit_ref, owner_id)
    return visit


def get_active_visits_for_mediator(mediator_id: int, db: Session) -> list[VisitRequest]:
    """Get all active visits for a mediator, auto-expiring stale ones."""
    visits = db.query(VisitRequest).filter(
        VisitRequest.mediator_id == mediator_id,
        VisitRequest.status.in_(["requested", "en_route", "arrived"]),
    ).order_by(VisitRequest.created_at.desc()).all()

    # Auto-expire any whose Redis holds are gone
    result = []
    for v in visits:
        hold = get_visit_hold(v.visit_ref)
        if hold is None:
            expire_visit(v.visit_ref, db)
            db.refresh(v)
        result.append(v)

    return result


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_active_visit(visit_ref: str, mediator_id: int, db: Session) -> VisitRequest:
    """Get an active visit request, validating ownership and hold status."""
    visit = db.query(VisitRequest).filter(
        VisitRequest.visit_ref == visit_ref,
    ).first()

    if not visit:
        raise VisitError("Visit not found", 404)
    if visit.mediator_id != mediator_id:
        raise VisitError("Not authorized to manage this visit", 403)
    if visit.status in ("booked", "passed", "expired", "owner_released"):
        raise VisitError(f"Visit is already {visit.status}")

    # Check Redis hold is still alive
    hold = get_visit_hold(visit_ref)
    if hold is None:
        expire_visit(visit_ref, db)
        db.refresh(visit)
        raise VisitError("Visit hold has expired")

    return visit
