# HillPing — Mediator Reliability Scoring Engine (V2)
#
# Mirrors the owner reliability system but with mediator-specific metrics:
# - Completion Rate (35%) — bookings where guest shows up / total
# - Guest Satisfaction (30%) — average guest rating of mediator
# - Response Speed (20%) — how fast mediator completes booking flow
# - Accuracy (15%) — bookings without disputes / total

import datetime
import logging
from datetime import timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy import func

from ..modals.mediator import MediatorReliabilityScore, MediatorPenalty
from ..modals.booking import Booking
from ..modals.trip_card import TripCard
from ..modals.visit import VisitRequest
from .platform_config import get_config_float, get_config_int

logger = logging.getLogger(__name__)


# ── Default weights (overridable via platform_config) ────────────────────────

def _get_weight(key: str, default: float, db: Session) -> float:
    try:
        return get_config_float(key, db)
    except Exception:
        return default


def calculate_mediator_score(mediator_id: int, db: Session) -> MediatorReliabilityScore:
    """Calculate and persist the mediator's reliability score."""

    w_completion = _get_weight("mediator_weight_completion", 0.35, db)
    w_satisfaction = _get_weight("mediator_weight_satisfaction", 0.30, db)
    w_speed = _get_weight("mediator_weight_speed", 0.20, db)
    w_accuracy = _get_weight("mediator_weight_accuracy", 0.15, db)

    # ── Completion rate ──────────────────────────────────────────────────
    total_bookings = db.query(func.count(Booking.id)).filter(
        Booking.mediator_id == mediator_id,
    ).scalar() or 0

    completed = db.query(func.count(Booking.id)).filter(
        Booking.mediator_id == mediator_id,
        Booking.status == "completed",
    ).scalar() or 0

    cancelled = db.query(func.count(Booking.id)).filter(
        Booking.mediator_id == mediator_id,
        Booking.status.in_(["cancelled_by_guest", "cancelled_by_owner"]),
    ).scalar() or 0

    if total_bookings > 0:
        completion_rate = (completed / total_bookings) * 100
    else:
        completion_rate = 100.0

    # ── Guest satisfaction ────────────────────────────────────────────────
    avg_rating = db.query(func.avg(TripCard.guest_rating_mediator)).filter(
        TripCard.mediator_id == mediator_id,
        TripCard.guest_rating_mediator.isnot(None),
    ).scalar()

    if avg_rating is not None:
        guest_satisfaction = float(avg_rating) / 5.0 * 100  # Normalize 1-5 → 0-100
    else:
        guest_satisfaction = 100.0  # No ratings yet, assume good

    # ── Response speed ───────────────────────────────────────────────────
    # Based on how many visits expired (mediator didn't show up in time)
    total_visits = db.query(func.count(VisitRequest.id)).filter(
        VisitRequest.mediator_id == mediator_id,
    ).scalar() or 0

    expired_visits = db.query(func.count(VisitRequest.id)).filter(
        VisitRequest.mediator_id == mediator_id,
        VisitRequest.status == "expired",
    ).scalar() or 0

    no_show_visits = expired_visits

    if total_visits > 0:
        response_speed = (1 - expired_visits / total_visits) * 100
    else:
        response_speed = 100.0

    # ── Accuracy ─────────────────────────────────────────────────────────
    # Bookings without disputes (cancellations count as inaccurate)
    disputed = db.query(func.count(Booking.id)).filter(
        Booking.mediator_id == mediator_id,
        Booking.status.in_(["cancelled_by_guest"]),  # Guest cancelled = possible mismatch
    ).scalar() or 0

    if total_bookings > 0:
        accuracy = (1 - disputed / total_bookings) * 100
    else:
        accuracy = 100.0

    # Clamp all to 0-100
    completion_rate = max(0.0, min(100.0, completion_rate))
    guest_satisfaction = max(0.0, min(100.0, guest_satisfaction))
    response_speed = max(0.0, min(100.0, response_speed))
    accuracy = max(0.0, min(100.0, accuracy))

    # ── Weighted total ───────────────────────────────────────────────────
    total_score = (
        w_completion * completion_rate
        + w_satisfaction * guest_satisfaction
        + w_speed * response_speed
        + w_accuracy * accuracy
    )
    total_score = round(total_score, 2)

    # Determine tier
    if total_score >= 90:
        tier = "star"
    elif total_score >= 70:
        tier = "trusted"
    elif total_score >= 50:
        tier = "needs_improvement"
    else:
        tier = "at_risk"

    # ── Upsert ───────────────────────────────────────────────────────────
    score_record = db.query(MediatorReliabilityScore).filter(
        MediatorReliabilityScore.mediator_id == mediator_id,
    ).first()

    now = datetime.datetime.now(timezone.utc)

    if not score_record:
        score_record = MediatorReliabilityScore(mediator_id=mediator_id)
        db.add(score_record)

    score_record.completion_rate = round(completion_rate, 2)
    score_record.guest_satisfaction = round(guest_satisfaction, 2)
    score_record.response_speed = round(response_speed, 2)
    score_record.accuracy = round(accuracy, 2)
    score_record.total_score = total_score
    score_record.score_tier = tier
    score_record.total_bookings = total_bookings
    score_record.completed_bookings = completed
    score_record.cancelled_bookings = cancelled
    score_record.disputed_bookings = disputed
    score_record.total_visits = total_visits
    score_record.no_show_visits = no_show_visits
    score_record.calculated_at = now

    db.commit()
    db.refresh(score_record)

    logger.info(
        "Mediator %d score: %.2f (%s) — C:%.0f S:%.0f R:%.0f A:%.0f",
        mediator_id, total_score, tier,
        completion_rate, guest_satisfaction, response_speed, accuracy,
    )

    return score_record


def check_and_apply_mediator_penalties(mediator_id: int, db: Session) -> list[MediatorPenalty]:
    """Check penalty conditions for a mediator."""
    now = datetime.datetime.now(timezone.utc)
    new_penalties = []

    score = db.query(MediatorReliabilityScore).filter(
        MediatorReliabilityScore.mediator_id == mediator_id,
    ).first()

    if not score:
        return []

    # No-show warning: >3 expired visits this week
    week_ago = now - timedelta(days=7)
    expired_this_week = db.query(func.count(VisitRequest.id)).filter(
        VisitRequest.mediator_id == mediator_id,
        VisitRequest.status == "expired",
        VisitRequest.created_at >= week_ago,
    ).scalar() or 0

    if expired_this_week >= 3:
        existing = db.query(MediatorPenalty).filter(
            MediatorPenalty.mediator_id == mediator_id,
            MediatorPenalty.penalty_type == "warning",
            MediatorPenalty.is_active == True,
            MediatorPenalty.issued_at >= week_ago,
        ).first()
        if not existing:
            penalty = MediatorPenalty(
                mediator_id=mediator_id,
                penalty_type="warning",
                reason=f"Expired {expired_this_week} visit holds this week (no-show)",
                expires_at=now + timedelta(days=7),
            )
            db.add(penalty)
            new_penalties.append(penalty)

    # Suspension: score below 50 for 2+ weeks
    if score.total_score < 50:
        existing = db.query(MediatorPenalty).filter(
            MediatorPenalty.mediator_id == mediator_id,
            MediatorPenalty.penalty_type == "suspension",
            MediatorPenalty.is_active == True,
        ).first()
        if not existing:
            suspended_until = now + timedelta(days=7)
            penalty = MediatorPenalty(
                mediator_id=mediator_id,
                penalty_type="suspension",
                reason=f"Reliability score {score.total_score} below threshold",
                expires_at=suspended_until,
            )
            db.add(penalty)
            new_penalties.append(penalty)

            score.is_suspended = True
            score.suspended_until = suspended_until

    if new_penalties:
        db.commit()
        logger.warning(
            "Issued %d penalties for mediator %d: %s",
            len(new_penalties), mediator_id,
            [p.penalty_type for p in new_penalties],
        )

    return new_penalties
