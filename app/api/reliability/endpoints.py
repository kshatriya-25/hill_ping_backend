# HillPing — Reliability Score endpoints

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...database.session import getdb
from ...modals.masters import User
from ...schemas.reliabilitySchema import ReliabilityScoreResponse, PenaltyResponse
from ...services.reliability import (
    get_owner_score,
    get_owner_penalties,
    calculate_reliability_score,
    check_and_apply_penalties,
    update_instant_confirm_eligibility,
    expire_old_penalties,
)
from ...utils.utils import get_current_user, require_owner, require_admin

router = APIRouter(tags=["reliability"])


@router.get("/my-score", response_model=ReliabilityScoreResponse)
def my_score(
    db: Session = Depends(getdb),
    current_user: User = Depends(require_owner),
):
    """Owner views their own reliability score."""
    score = get_owner_score(current_user.id, db)
    if not score:
        raise HTTPException(status_code=404, detail="No score calculated yet")
    return score


@router.get("/my-penalties", response_model=list[PenaltyResponse])
def my_penalties(
    db: Session = Depends(getdb),
    current_user: User = Depends(require_owner),
):
    """Owner views their active penalties."""
    return get_owner_penalties(current_user.id, db, active_only=True)


@router.get("/score/{owner_id}", response_model=ReliabilityScoreResponse)
def view_score(
    owner_id: int,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """Admin or the owner themselves can view a score."""
    if current_user.role != "admin" and current_user.id != owner_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    score = get_owner_score(owner_id, db)
    if not score:
        raise HTTPException(status_code=404, detail="No score calculated yet")
    return score


@router.get("/penalties/{owner_id}", response_model=list[PenaltyResponse])
def view_penalties(
    owner_id: int,
    active_only: bool = True,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin views penalty history for an owner."""
    return get_owner_penalties(owner_id, db, active_only=active_only)


@router.post("/recalculate/{owner_id}", response_model=ReliabilityScoreResponse)
def recalculate_score(
    owner_id: int,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """
    Admin triggers a recalculation for a specific owner.
    In production, this will aggregate from ping_sessions and bookings tables.
    For now, it recalculates with whatever raw counts are stored.
    """
    existing = get_owner_score(owner_id, db)
    if existing:
        # Recalculate with stored raw counts
        score = calculate_reliability_score(
            owner_id, db,
            total_pings=existing.total_pings,
            accepted_pings=existing.accepted_pings,
            rejected_pings=existing.rejected_pings,
            expired_pings=existing.expired_pings,
            total_confirmed_bookings=existing.total_bookings,
            cancelled_after_accept=existing.cancelled_bookings,
        )
    else:
        # Fresh score for new owner
        score = calculate_reliability_score(owner_id, db)

    update_instant_confirm_eligibility(owner_id, db)
    return score


@router.post("/expire-penalties")
def expire_penalties(
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin triggers cleanup of expired penalties."""
    count = expire_old_penalties(db)
    return {"detail": f"Expired {count} penalties"}
