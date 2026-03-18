# HillPing — Tour Session Service (V2)
#
# Multi-property tour orchestration:
# 1. Mediator starts tour with 2-3 properties
# 2. Visit requests created for all stops (holds start simultaneously)
# 3. Mediator visits sequentially, books or passes
# 4. Booking any stop releases all remaining holds
# 5. Tour has a single 45-minute time budget

import datetime
import logging
import secrets
import string
from datetime import timedelta, timezone

from sqlalchemy.orm import Session

from ..core.config import settings
from ..modals.tour import TourSession, TourStop
from ..modals.visit import VisitRequest
from ..services.visit import (
    create_visit_request, pass_visit, book_from_visit,
    arrive_at_property, extend_visit, VisitError,
)
from ..database.redis import get_visit_hold, delete_visit_hold, extend_visit_hold

logger = logging.getLogger(__name__)


class TourError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code


def _generate_tour_ref() -> str:
    chars = string.ascii_uppercase + string.digits
    return "T-" + "".join(secrets.choice(chars) for _ in range(6))


def start_tour(
    mediator_id: int,
    property_ids: list[int],
    guest_id: int | None,
    guest_count: int,
    eta_minutes: int | None,
    db: Session,
) -> TourSession:
    """Start a multi-property tour. Creates tour session + visit requests for all stops."""
    if len(property_ids) > settings.MAX_TOUR_STOPS:
        raise TourError(f"Maximum {settings.MAX_TOUR_STOPS} stops per tour")
    if len(property_ids) < 1:
        raise TourError("At least 1 property required")

    tour_ref = _generate_tour_ref()
    while db.query(TourSession).filter(TourSession.tour_ref == tour_ref).first():
        tour_ref = _generate_tour_ref()

    now = datetime.datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.VISIT_HOLD_TTL_SECONDS)

    tour = TourSession(
        tour_ref=tour_ref,
        mediator_id=mediator_id,
        guest_id=guest_id,
        status="active",
        total_stops=len(property_ids),
        current_stop_index=0,
        expires_at=expires_at,
    )
    db.add(tour)
    db.flush()  # get tour.id

    # Create visit requests for all stops
    stops = []
    for idx, prop_id in enumerate(property_ids):
        try:
            visit = create_visit_request(
                mediator_id=mediator_id,
                property_id=prop_id,
                room_id=None,
                guest_id=guest_id,
                guest_count=guest_count,
                eta_minutes=eta_minutes,
                ping_session_id=None,
                tour_session_id=tour.id,
                tour_stop_order=idx,
                db=db,
            )
            stop = TourStop(
                tour_id=tour.id,
                stop_index=idx,
                visit_request_id=visit.id,
                property_id=prop_id,
                status="pending" if idx > 0 else "active",
            )
            if idx == 0:
                stop.started_at = now
            db.add(stop)
            stops.append(stop)
        except VisitError as e:
            logger.warning("Tour stop skipped property %d: %s", prop_id, e.detail)
            continue

    if not stops:
        db.rollback()
        raise TourError("No properties could be added to the tour")

    tour.total_stops = len(stops)
    db.commit()
    db.refresh(tour)

    logger.info(
        "Tour %s started by mediator %d with %d stops",
        tour_ref, mediator_id, len(stops),
    )
    return tour


def next_stop(tour_ref: str, mediator_id: int, reason: str | None, db: Session) -> TourSession:
    """Pass on current stop and advance to next."""
    tour = _get_active_tour(tour_ref, mediator_id, db)

    current_stop = _get_current_stop(tour, db)
    if not current_stop:
        raise TourError("No current stop found")

    # Pass the current visit
    visit = db.query(VisitRequest).filter(
        VisitRequest.id == current_stop.visit_request_id,
    ).first()
    if visit and visit.status in ("requested", "en_route", "arrived"):
        try:
            pass_visit(visit.visit_ref, mediator_id, reason, db)
        except VisitError:
            pass  # Already expired, that's fine

    current_stop.status = "passed"
    current_stop.ended_at = datetime.datetime.now(timezone.utc)

    # Advance to next stop
    tour.current_stop_index += 1
    next_idx = tour.current_stop_index

    next_stop_record = db.query(TourStop).filter(
        TourStop.tour_id == tour.id,
        TourStop.stop_index == next_idx,
    ).first()

    if not next_stop_record:
        # No more stops — end tour
        tour.status = "completed"
        tour.completed_at = datetime.datetime.now(timezone.utc)
    else:
        next_stop_record.status = "active"
        next_stop_record.started_at = datetime.datetime.now(timezone.utc)

    db.commit()
    db.refresh(tour)

    return tour


def book_from_tour(tour_ref: str, mediator_id: int, db: Session) -> TourSession:
    """Book the current stop — releases all remaining holds, ends tour."""
    tour = _get_active_tour(tour_ref, mediator_id, db)

    current_stop = _get_current_stop(tour, db)
    if not current_stop:
        raise TourError("No current stop found")

    # Book the current visit
    visit = db.query(VisitRequest).filter(
        VisitRequest.id == current_stop.visit_request_id,
    ).first()
    if visit:
        try:
            book_from_visit(visit.visit_ref, mediator_id, db)
        except VisitError as e:
            raise TourError(e.detail, e.status_code)

    current_stop.status = "booked"
    current_stop.ended_at = datetime.datetime.now(timezone.utc)

    # Release all other holds
    other_stops = db.query(TourStop).filter(
        TourStop.tour_id == tour.id,
        TourStop.id != current_stop.id,
        TourStop.status.in_(["pending", "active"]),
    ).all()

    for stop in other_stops:
        stop.status = "skipped"
        stop.ended_at = datetime.datetime.now(timezone.utc)
        # Release the visit hold
        other_visit = db.query(VisitRequest).filter(
            VisitRequest.id == stop.visit_request_id,
        ).first()
        if other_visit and other_visit.status in ("requested", "en_route", "arrived"):
            other_visit.status = "passed"
            other_visit.pass_reason = "tour_booked_elsewhere"
            other_visit.decided_at = datetime.datetime.now(timezone.utc)
            delete_visit_hold(other_visit.visit_ref)

    tour.status = "completed"
    tour.completed_at = datetime.datetime.now(timezone.utc)
    tour.booked_property_id = current_stop.property_id
    db.commit()
    db.refresh(tour)

    logger.info("Tour %s: booked property %d, released %d other holds",
                tour_ref, current_stop.property_id, len(other_stops))
    return tour


def extend_tour(tour_ref: str, mediator_id: int, db: Session) -> TourSession:
    """Extend tour time by 15 minutes (once per tour)."""
    tour = _get_active_tour(tour_ref, mediator_id, db)

    if tour.extended:
        raise TourError("Tour can only be extended once")

    extension_seconds = 900  # 15 minutes

    # Extend all active visit holds
    stops = db.query(TourStop).filter(
        TourStop.tour_id == tour.id,
        TourStop.status.in_(["pending", "active"]),
    ).all()

    for stop in stops:
        visit = db.query(VisitRequest).filter(
            VisitRequest.id == stop.visit_request_id,
        ).first()
        if visit:
            extend_visit_hold(visit.visit_ref, extension_seconds)
            visit.hold_expires_at += timedelta(seconds=extension_seconds)
            visit.hold_extended = True

    tour.extended = True
    tour.expires_at += timedelta(seconds=extension_seconds)
    db.commit()
    db.refresh(tour)

    return tour


def end_tour(tour_ref: str, mediator_id: int, db: Session) -> TourSession:
    """End tour early — releases all remaining holds."""
    tour = _get_active_tour(tour_ref, mediator_id, db)

    active_stops = db.query(TourStop).filter(
        TourStop.tour_id == tour.id,
        TourStop.status.in_(["pending", "active"]),
    ).all()

    for stop in active_stops:
        stop.status = "skipped"
        stop.ended_at = datetime.datetime.now(timezone.utc)
        visit = db.query(VisitRequest).filter(
            VisitRequest.id == stop.visit_request_id,
        ).first()
        if visit and visit.status in ("requested", "en_route", "arrived"):
            visit.status = "passed"
            visit.pass_reason = "tour_ended"
            visit.decided_at = datetime.datetime.now(timezone.utc)
            delete_visit_hold(visit.visit_ref)

    tour.status = "abandoned"
    tour.completed_at = datetime.datetime.now(timezone.utc)
    db.commit()
    db.refresh(tour)

    return tour


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_active_tour(tour_ref: str, mediator_id: int, db: Session) -> TourSession:
    tour = db.query(TourSession).filter(TourSession.tour_ref == tour_ref).first()
    if not tour:
        raise TourError("Tour not found", 404)
    if tour.mediator_id != mediator_id:
        raise TourError("Not authorized", 403)
    if tour.status != "active":
        raise TourError(f"Tour is already {tour.status}")
    return tour


def _get_current_stop(tour: TourSession, db: Session) -> TourStop | None:
    return db.query(TourStop).filter(
        TourStop.tour_id == tour.id,
        TourStop.stop_index == tour.current_stop_index,
    ).first()
