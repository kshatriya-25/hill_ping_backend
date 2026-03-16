# HillPing — Owner Reliability Scoring Engine
#
# ALL scoring weights, thresholds, and penalty rules are admin-configurable
# via the platform_config table. No hardcoded constants.
#
# Admin can tune from /api/admin/config:
#   weight_acceptance, weight_response_time, weight_cancellation, weight_status_accuracy
#   response_time_max_seconds, instant_confirm_threshold
#   missed_pings_warning, rejections_rank_drop, cancellations_suspension, suspension_days
#   low_score_threshold, low_score_delist_weeks

import datetime
import logging
from datetime import timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..modals.reliability import OwnerReliabilityScore, OwnerPenalty
from ..modals.property import Property
from .platform_config import get_config_float, get_config_int

logger = logging.getLogger(__name__)


# ── Core scoring functions ────────────────────────────────────────────────────

def normalize_response_time(avg_seconds: float, db: Session) -> float:
    """
    Linear normalization: 0 seconds → 100 (perfect), max_seconds → 0 (worst).
    max_seconds is admin-configurable via 'response_time_max_seconds'.
    """
    max_seconds = get_config_float("response_time_max_seconds", db)
    if max_seconds <= 0:
        max_seconds = 30.0
    if avg_seconds <= 0:
        return 100.0
    return max(0.0, (1 - avg_seconds / max_seconds) * 100)


def get_score_tier(score: float, db: Session) -> str:
    """Map a 0-100 score to its tier label."""
    low_threshold = get_config_float("low_score_threshold", db)
    if score >= 90:
        return "reliable"
    if score >= 70:
        return "good"
    if score >= low_threshold:
        return "needs_improvement"
    return "at_risk"


def calculate_reliability_score(
    owner_id: int,
    db: Session,
    *,
    total_pings: int = 0,
    accepted_pings: int = 0,
    rejected_pings: int = 0,
    expired_pings: int = 0,
    avg_response_seconds: float = 0.0,
    total_confirmed_bookings: int = 0,
    cancelled_after_accept: int = 0,
    missed_while_online: int = 0,
    total_while_online: int = 0,
) -> OwnerReliabilityScore:
    """
    Calculate and persist the reliability score for an owner.
    All weights and thresholds are read from admin-configurable platform_config.
    """
    # ── Read weights from config ──────────────────────────────────────────
    w_acceptance = get_config_float("weight_acceptance", db)
    w_response = get_config_float("weight_response_time", db)
    w_cancellation = get_config_float("weight_cancellation", db)
    w_accuracy = get_config_float("weight_status_accuracy", db)

    low_threshold = get_config_float("low_score_threshold", db)

    # ── Compute individual metrics ────────────────────────────────────────
    if total_pings > 0:
        acceptance_rate = (accepted_pings / total_pings) * 100
    else:
        acceptance_rate = 100.0

    response_time_score = normalize_response_time(avg_response_seconds, db)

    if total_confirmed_bookings > 0:
        cancellation_score = (1 - cancelled_after_accept / total_confirmed_bookings) * 100
    else:
        cancellation_score = 100.0

    if total_while_online > 0:
        status_accuracy = (1 - missed_while_online / total_while_online) * 100
    else:
        status_accuracy = 100.0

    # Clamp all to 0-100
    acceptance_rate = max(0.0, min(100.0, acceptance_rate))
    response_time_score = max(0.0, min(100.0, response_time_score))
    cancellation_score = max(0.0, min(100.0, cancellation_score))
    status_accuracy = max(0.0, min(100.0, status_accuracy))

    # ── Weighted total ────────────────────────────────────────────────────
    total_score = (
        w_acceptance * acceptance_rate
        + w_response * response_time_score
        + w_cancellation * cancellation_score
        + w_accuracy * status_accuracy
    )
    total_score = round(total_score, 2)
    tier = get_score_tier(total_score, db)

    # ── Upsert score record ───────────────────────────────────────────────
    score_record = db.query(OwnerReliabilityScore).filter(
        OwnerReliabilityScore.owner_id == owner_id
    ).first()

    now = datetime.datetime.now(timezone.utc)

    if not score_record:
        score_record = OwnerReliabilityScore(owner_id=owner_id)
        db.add(score_record)

    score_record.acceptance_rate = round(acceptance_rate, 2)
    score_record.avg_response_time = round(response_time_score, 2)
    score_record.cancellation_rate = round(cancellation_score, 2)
    score_record.status_accuracy = round(status_accuracy, 2)
    score_record.total_score = total_score
    score_record.score_tier = tier
    score_record.total_pings = total_pings
    score_record.accepted_pings = accepted_pings
    score_record.rejected_pings = rejected_pings
    score_record.expired_pings = expired_pings
    score_record.total_bookings = total_confirmed_bookings
    score_record.cancelled_bookings = cancelled_after_accept
    score_record.calculated_at = now

    # Track consecutive low-score weeks for delist logic
    if total_score < low_threshold:
        score_record.consecutive_low_weeks += 1
    else:
        score_record.consecutive_low_weeks = 0

    db.commit()
    db.refresh(score_record)

    logger.info(
        "Reliability score for owner %d: %.2f (%s) — A:%.0f R:%.0f C:%.0f S:%.0f [weights: %.2f/%.2f/%.2f/%.2f]",
        owner_id, total_score, tier, acceptance_rate, response_time_score,
        cancellation_score, status_accuracy, w_acceptance, w_response, w_cancellation, w_accuracy,
    )

    return score_record


def update_instant_confirm_eligibility(owner_id: int, db: Session) -> bool:
    """
    If owner's acceptance rate >= admin-configured threshold,
    enable instant confirm on all their properties.
    """
    score = db.query(OwnerReliabilityScore).filter(
        OwnerReliabilityScore.owner_id == owner_id
    ).first()

    if not score:
        return False

    threshold = get_config_float("instant_confirm_threshold", db)
    should_enable = score.acceptance_rate >= threshold and score.total_score >= 90

    db.query(Property).filter(Property.owner_id == owner_id).update(
        {"is_instant_confirm": should_enable}
    )
    db.commit()

    if should_enable:
        logger.info("Instant confirm ENABLED for owner %d (acceptance: %.1f%%, threshold: %.1f%%)",
                     owner_id, score.acceptance_rate, threshold)

    return should_enable


# ── Penalty engine ────────────────────────────────────────────────────────────

def check_and_apply_penalties(
    owner_id: int,
    db: Session,
    *,
    missed_pings_this_week: int = 0,
    rejections_this_month: int = 0,
    cancellations_this_month: int = 0,
) -> list[OwnerPenalty]:
    """
    Check penalty conditions and issue penalties if thresholds are breached.
    All thresholds are admin-configurable.
    """
    now = datetime.datetime.now(timezone.utc)
    new_penalties = []

    # ── Read thresholds from config ───────────────────────────────────────
    missed_threshold = get_config_int("missed_pings_warning", db)
    rejection_threshold = get_config_int("rejections_rank_drop", db)
    cancel_threshold = get_config_int("cancellations_suspension", db)
    suspend_days = get_config_int("suspension_days", db)
    low_threshold = get_config_float("low_score_threshold", db)
    delist_weeks = get_config_int("low_score_delist_weeks", db)

    score_record = db.query(OwnerReliabilityScore).filter(
        OwnerReliabilityScore.owner_id == owner_id
    ).first()

    # ── 1. Missed pings warning ───────────────────────────────────────────
    if missed_pings_this_week >= missed_threshold:
        existing = db.query(OwnerPenalty).filter(
            OwnerPenalty.owner_id == owner_id,
            OwnerPenalty.penalty_type == "warning",
            OwnerPenalty.is_active == True,
            OwnerPenalty.issued_at >= now - timedelta(days=7),
        ).first()
        if not existing:
            penalty = OwnerPenalty(
                owner_id=owner_id,
                penalty_type="warning",
                reason=f"Missed {missed_pings_this_week} pings this week (threshold: {missed_threshold})",
                expires_at=now + timedelta(days=7),
            )
            db.add(penalty)
            new_penalties.append(penalty)

    # ── 2. Rejection rank drop ────────────────────────────────────────────
    if rejections_this_month >= rejection_threshold:
        existing = db.query(OwnerPenalty).filter(
            OwnerPenalty.owner_id == owner_id,
            OwnerPenalty.penalty_type == "rank_drop",
            OwnerPenalty.is_active == True,
            OwnerPenalty.issued_at >= now - timedelta(days=30),
        ).first()
        if not existing:
            penalty = OwnerPenalty(
                owner_id=owner_id,
                penalty_type="rank_drop",
                reason=f"Rejected {rejections_this_month} bookings this month (threshold: {rejection_threshold})",
                expires_at=now + timedelta(days=30),
            )
            db.add(penalty)
            new_penalties.append(penalty)

    # ── 3. Cancellation suspension ────────────────────────────────────────
    if cancellations_this_month >= cancel_threshold:
        existing = db.query(OwnerPenalty).filter(
            OwnerPenalty.owner_id == owner_id,
            OwnerPenalty.penalty_type == "suspension",
            OwnerPenalty.is_active == True,
        ).first()
        if not existing:
            suspended_until = now + timedelta(days=suspend_days)
            penalty = OwnerPenalty(
                owner_id=owner_id,
                penalty_type="suspension",
                reason=f"Cancelled {cancellations_this_month} bookings after acceptance this month",
                expires_at=suspended_until,
            )
            db.add(penalty)
            new_penalties.append(penalty)

            if score_record:
                score_record.is_suspended = True
                score_record.suspended_until = suspended_until

            db.query(Property).filter(Property.owner_id == owner_id).update({"status": "offline"})

    # ── 4. Delist for consecutive low score ───────────────────────────────
    if score_record and score_record.consecutive_low_weeks >= delist_weeks:
        existing = db.query(OwnerPenalty).filter(
            OwnerPenalty.owner_id == owner_id,
            OwnerPenalty.penalty_type == "delist",
            OwnerPenalty.is_active == True,
        ).first()
        if not existing:
            penalty = OwnerPenalty(
                owner_id=owner_id,
                penalty_type="delist",
                reason=f"Score below {low_threshold} for {score_record.consecutive_low_weeks} consecutive weeks",
            )
            db.add(penalty)
            new_penalties.append(penalty)

            db.query(Property).filter(Property.owner_id == owner_id).update({"status": "offline"})
            score_record.is_suspended = True

    if new_penalties:
        db.commit()
        logger.warning(
            "Issued %d penalties for owner %d: %s",
            len(new_penalties), owner_id,
            [p.penalty_type for p in new_penalties],
        )

    return new_penalties


def get_owner_score(owner_id: int, db: Session) -> OwnerReliabilityScore | None:
    """Fetch the current reliability score for an owner."""
    return db.query(OwnerReliabilityScore).filter(
        OwnerReliabilityScore.owner_id == owner_id
    ).first()


def get_owner_penalties(owner_id: int, db: Session, active_only: bool = True) -> list[OwnerPenalty]:
    """Fetch penalties for an owner."""
    q = db.query(OwnerPenalty).filter(OwnerPenalty.owner_id == owner_id)
    if active_only:
        q = q.filter(OwnerPenalty.is_active == True)
    return q.order_by(OwnerPenalty.issued_at.desc()).all()


def expire_old_penalties(db: Session) -> int:
    """Deactivate penalties past their expiry date. Returns count of expired penalties."""
    now = datetime.datetime.now(timezone.utc)
    count = db.query(OwnerPenalty).filter(
        OwnerPenalty.is_active == True,
        OwnerPenalty.expires_at != None,
        OwnerPenalty.expires_at < now,
    ).update({"is_active": False})

    expired_suspensions = db.query(OwnerPenalty).filter(
        OwnerPenalty.penalty_type == "suspension",
        OwnerPenalty.is_active == False,
    ).all()
    for p in expired_suspensions:
        score = db.query(OwnerReliabilityScore).filter(
            OwnerReliabilityScore.owner_id == p.owner_id,
            OwnerReliabilityScore.is_suspended == True,
        ).first()
        if score and score.suspended_until and score.suspended_until < now:
            score.is_suspended = False
            score.suspended_until = None

    db.commit()
    return count
