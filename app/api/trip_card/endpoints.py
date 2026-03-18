# HillPing — Trip Card endpoints (V2)

import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.orm import Session

from ...database.session import getdb
from ...modals.masters import User
from ...services.trip_card import (
    update_en_route, mark_arrived, check_in, complete_trip,
    cancel_trip, rate_stay, rate_mediator, TripCardError,
)
from ...utils.utils import get_current_user, require_role

router = APIRouter(tags=["trip-card"])
logger = logging.getLogger(__name__)


class EnRouteRequest(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    eta_minutes: Optional[int] = Field(default=None, ge=1, le=300)


class RateStayRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=1000)


class RateMediatorRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)


@router.get("/{card_ref}")
def get_trip_card(
    card_ref: str,
    db: Session = Depends(getdb),
):
    """Get Trip Card data (public — identified by card_ref)."""
    from ...modals.trip_card import TripCard
    from ...modals.property import Property

    card = db.query(TripCard).filter(TripCard.card_ref == card_ref).first()
    if not card:
        raise HTTPException(status_code=404, detail="Trip card not found")

    prop = db.query(Property).filter(Property.id == card.property_id).first()

    return {
        "card_ref": card.card_ref,
        "booking_id": card.booking_id,
        "status": card.status,
        "property": {
            "id": prop.id if prop else None,
            "name": prop.name if prop else None,
            "address": prop.address if prop else None,
            "latitude": prop.latitude if prop else None,
            "longitude": prop.longitude if prop else None,
        } if prop else None,
        "guest_id": card.guest_id,
        "mediator_id": card.mediator_id,
        "owner_id": card.owner_id,
        "estimated_arrival_minutes": card.estimated_arrival_minutes,
        "check_in_time": card.check_in_time.isoformat() if card.check_in_time else None,
        "check_out_time": card.check_out_time.isoformat() if card.check_out_time else None,
        "check_in_instructions": card.check_in_instructions,
        "guest_rating_stay": card.guest_rating_stay,
        "guest_rating_mediator": card.guest_rating_mediator,
        "created_at": card.created_at.isoformat() if card.created_at else None,
    }


@router.post("/{card_ref}/en-route")
def en_route(
    card_ref: str,
    data: EnRouteRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(getdb),
):
    """Guest taps 'I'm on my way' — updates status, notifies owner."""
    try:
        card = update_en_route(card_ref, data.latitude, data.longitude, data.eta_minutes, db)
    except TripCardError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    from ...api.ws.connection_manager import ws_manager
    background_tasks.add_task(
        ws_manager.send_to_user,
        card.owner_id,
        {
            "type": "guest_en_route",
            "card_ref": card_ref,
            "eta_minutes": data.eta_minutes,
        },
    )

    return {"detail": "Status updated to en_route", "status": card.status}


@router.post("/{card_ref}/arrived")
def arrived(
    card_ref: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(getdb),
):
    """Guest arrived at property."""
    try:
        card = mark_arrived(card_ref, db)
    except TripCardError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    from ...api.ws.connection_manager import ws_manager
    background_tasks.add_task(
        ws_manager.send_to_user,
        card.owner_id,
        {"type": "guest_arrived", "card_ref": card_ref},
    )

    return {"detail": "Status updated to arrived", "status": card.status}


@router.post("/{card_ref}/check-in")
def check_in_endpoint(
    card_ref: str,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("owner")),
):
    """Owner confirms guest check-in."""
    try:
        card = check_in(card_ref, current_user.id, db)
    except TripCardError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    return {"detail": "Guest checked in", "status": card.status}


@router.post("/{card_ref}/cancel")
def cancel(
    card_ref: str,
    db: Session = Depends(getdb),
):
    """Guest cancels trip."""
    try:
        card = cancel_trip(card_ref, db)
    except TripCardError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    return {"detail": "Trip cancelled", "status": card.status}


@router.post("/{card_ref}/rate-stay")
def rate_stay_endpoint(
    card_ref: str,
    data: RateStayRequest,
    db: Session = Depends(getdb),
):
    """Guest rates the property stay (1-5, unlocked after checkout)."""
    try:
        card = rate_stay(card_ref, data.rating, data.comment, db)
    except TripCardError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    return {"detail": "Stay rated", "rating": card.guest_rating_stay}


@router.post("/{card_ref}/rate-mediator")
def rate_mediator_endpoint(
    card_ref: str,
    data: RateMediatorRequest,
    db: Session = Depends(getdb),
):
    """Guest rates the mediator (1-5)."""
    try:
        card = rate_mediator(card_ref, data.rating, db)
    except TripCardError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    return {"detail": "Mediator rated", "rating": card.guest_rating_mediator}
