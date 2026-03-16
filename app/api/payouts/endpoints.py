# HillPing — Payout endpoints

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...database.session import getdb
from ...modals.masters import User
from ...modals.booking import Payout, Booking
from ...schemas.bookingSchema import PayoutResponse
from ...utils.utils import require_owner, require_admin

router = APIRouter(tags=["payouts"])


@router.get("/my", response_model=list[PayoutResponse])
def my_payouts(
    status: str = Query(default=None),
    db: Session = Depends(getdb),
    current_user: User = Depends(require_owner),
):
    """Owner views their payout history."""
    q = db.query(Payout).filter(Payout.owner_id == current_user.id)
    if status:
        q = q.filter(Payout.status == status)
    payouts = q.order_by(Payout.created_at.desc()).all()

    result = []
    for p in payouts:
        booking = db.query(Booking).filter(Booking.id == p.booking_id).first()
        result.append(PayoutResponse(
            id=p.id,
            owner_id=p.owner_id,
            booking_id=p.booking_id,
            booking_ref=booking.booking_ref if booking else None,
            gross_amount=p.gross_amount,
            commission_amount=p.commission_amount,
            net_amount=p.net_amount,
            status=p.status,
            payout_date=p.payout_date,
            created_at=p.created_at,
        ))
    return result


@router.get("/pending", response_model=list[PayoutResponse])
def pending_payouts(
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin views all pending payouts."""
    payouts = db.query(Payout).filter(Payout.status == "pending").order_by(Payout.created_at).all()
    result = []
    for p in payouts:
        booking = db.query(Booking).filter(Booking.id == p.booking_id).first()
        result.append(PayoutResponse(
            id=p.id,
            owner_id=p.owner_id,
            booking_id=p.booking_id,
            booking_ref=booking.booking_ref if booking else None,
            gross_amount=p.gross_amount,
            commission_amount=p.commission_amount,
            net_amount=p.net_amount,
            status=p.status,
            payout_date=p.payout_date,
            created_at=p.created_at,
        ))
    return result


@router.post("/{payout_id}/process")
def process_payout(
    payout_id: int,
    db: Session = Depends(getdb),
    _admin: User = Depends(require_admin),
):
    """Admin marks a payout as processed."""
    import datetime
    from datetime import timezone

    payout = db.query(Payout).filter(Payout.id == payout_id).first()
    if not payout:
        raise HTTPException(status_code=404, detail="Payout not found")
    if payout.status != "pending":
        raise HTTPException(status_code=400, detail=f"Payout already {payout.status}")

    payout.status = "processed"
    payout.payout_date = datetime.datetime.now(timezone.utc)
    db.commit()
    return {"detail": f"Payout {payout_id} processed (₹{payout.net_amount})"}
