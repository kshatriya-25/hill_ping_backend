# HillPing — Tour Session endpoints (V2)

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...database.session import getdb
from ...modals.masters import User
from ...schemas.tourSchema import (
    TourStartRequest,
    TourNextStopRequest,
    TourSessionResponse,
)
from ...services.tour import (
    start_tour, next_stop, book_from_tour,
    extend_tour, end_tour, TourError,
)
from ...utils.utils import require_role

router = APIRouter(tags=["tour"])
logger = logging.getLogger(__name__)


@router.post("/start", response_model=TourSessionResponse, status_code=201)
def start_tour_endpoint(
    data: TourStartRequest,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Start a multi-property tour (max 3 stops)."""
    try:
        tour = start_tour(
            mediator_id=current_user.id,
            property_ids=data.property_ids,
            guest_id=data.guest_id,
            guest_count=data.guest_count,
            eta_minutes=data.eta_minutes,
            db=db,
        )
    except TourError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    return tour


@router.post("/{tour_ref}/next-stop", response_model=TourSessionResponse)
def advance_to_next_stop(
    tour_ref: str,
    data: TourNextStopRequest,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Pass on current stop, advance to next."""
    try:
        tour = next_stop(tour_ref, current_user.id, data.reason, db)
    except TourError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    return tour


@router.post("/{tour_ref}/book", response_model=TourSessionResponse)
def book_current_stop(
    tour_ref: str,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Book the current stop — releases all remaining holds."""
    try:
        tour = book_from_tour(tour_ref, current_user.id, db)
    except TourError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    return tour


@router.post("/{tour_ref}/extend", response_model=TourSessionResponse)
def extend_tour_endpoint(
    tour_ref: str,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Extend tour time by 15 minutes (once per tour)."""
    try:
        tour = extend_tour(tour_ref, current_user.id, db)
    except TourError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    return tour


@router.post("/{tour_ref}/end", response_model=TourSessionResponse)
def end_tour_endpoint(
    tour_ref: str,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """End tour early — releases all remaining holds."""
    try:
        tour = end_tour(tour_ref, current_user.id, db)
    except TourError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    return tour


@router.get("/{tour_ref}/status", response_model=TourSessionResponse)
def get_tour_status(
    tour_ref: str,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """Get tour session status with all stops."""
    from ...modals.tour import TourSession

    tour = db.query(TourSession).filter(
        TourSession.tour_ref == tour_ref,
    ).first()
    if not tour:
        raise HTTPException(status_code=404, detail="Tour not found")
    if tour.mediator_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    return tour
