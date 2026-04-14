# HillPing — Visit Card endpoints (V2)

import datetime
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.orm import Session

from ...database.session import getdb
from ...modals.masters import User
from ...modals.guest_access import VisitCard
from ...services.guest_access import create_visit_card, GuestAccessError
from ...services.sms import send_visit_card_sms
from ...utils.utils import require_role

router = APIRouter(tags=["visit-card"])
logger = logging.getLogger(__name__)


class VisitCardCreateRequest(BaseModel):
    guest_phone: str = Field(..., max_length=15)
    guest_name: str = Field(..., min_length=1, max_length=100)
    guest_count: int = Field(default=1, ge=1, le=20)


class GuestChoiceRequest(BaseModel):
    property_id: int


@router.post("/create", status_code=201)
def create_card(
    data: VisitCardCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("mediator")),
):
    """
    Mediator registers a guest — creates Visit Card + access code + sends SMS.
    This is the FIRST thing a mediator does when meeting a tourist.
    """
    try:
        card, raw_code, auto_login_token = create_visit_card(
            mediator_id=current_user.id,
            guest_phone=data.guest_phone,
            guest_name=data.guest_name,
            guest_count=data.guest_count,
            db=db,
        )
    except GuestAccessError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    # Build card URL
    card_url = f"hillping.in/v/{card.card_ref}?t={auto_login_token}"

    # Send SMS in background
    background_tasks.add_task(
        send_visit_card_sms,
        data.guest_phone,
        data.guest_name,
        card_url,
        raw_code,
        current_user.name,
    )

    return {
        "card_ref": card.card_ref,
        "guest_id": card.guest_id,
        "access_code": raw_code,
        "card_url": card_url,
        "auto_login_token": auto_login_token,
        "expires_at": card.expires_at.isoformat() if card.expires_at else None,
    }


@router.get("/{card_ref}")
def get_card(
    card_ref: str,
    db: Session = Depends(getdb),
):
    """
    Get Visit Card data (public — auto-authenticated via URL token).
    This is the tourist's live view of their property tour.
    """
    card = db.query(VisitCard).filter(VisitCard.card_ref == card_ref).first()
    if not card:
        raise HTTPException(status_code=404, detail="Visit card not found")

    # Track card opens
    if card.card_opened_at is None:
        card.card_opened_at = datetime.datetime.now(datetime.timezone.utc)
    card.card_open_count += 1
    db.commit()

    return {
        "card_ref": card.card_ref,
        "guest_name": card.guest_name,
        "guest_count": card.guest_count,
        "mediator_id": card.mediator_id,
        "status": card.status,
        "guest_choice_property_id": card.guest_choice_property_id,
        "tour_session_id": card.tour_session_id,
        "card_open_count": card.card_open_count,
        "created_at": card.created_at.isoformat() if card.created_at else None,
    }


@router.post("/{card_ref}/choose")
def guest_choice(
    card_ref: str,
    data: GuestChoiceRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(getdb),
):
    """Tourist taps 'I Want This One' — records their property choice."""
    card = db.query(VisitCard).filter(VisitCard.card_ref == card_ref).first()
    if not card:
        raise HTTPException(status_code=404, detail="Visit card not found")

    card.guest_choice_property_id = data.property_id
    card.guest_choice_at = datetime.datetime.now(datetime.timezone.utc)
    card.status = "choice_made"
    db.commit()

    # Notify mediator
    from ...api.ws.connection_manager import ws_manager
    background_tasks.add_task(
        ws_manager.send_to_user,
        card.mediator_id,
        {
            "type": "guest_chose_property",
            "card_ref": card_ref,
            "property_id": data.property_id,
            "guest_name": card.guest_name,
        },
    )

    return {"detail": "Choice recorded", "property_id": data.property_id}


@router.get("/{card_ref}/compare")
def compare_properties(
    card_ref: str,
    db: Session = Depends(getdb),
):
    """Get price comparison table for all properties in the tour."""
    card = db.query(VisitCard).filter(VisitCard.card_ref == card_ref).first()
    if not card:
        raise HTTPException(status_code=404, detail="Visit card not found")

    if not card.tour_session_id:
        return {"properties": []}

    from ...modals.tour import TourStop
    from ...modals.property import Property, Room
    stops = db.query(TourStop).filter(
        TourStop.tour_id == card.tour_session_id,
    ).order_by(TourStop.stop_index).all()

    comparisons = []
    for stop in stops:
        prop = db.query(Property).filter(Property.id == stop.property_id).first()
        if not prop:
            continue

        from ...services.pricing import room_min_guest_nightly

        rooms_avail = db.query(Room).filter(
            Room.property_id == prop.id, Room.is_available == True,
        ).all()
        min_price = min((room_min_guest_nightly(r) for r in rooms_avail), default=None) if rooms_avail else None

        comparisons.append({
            "property_id": prop.id,
            "name": prop.name,
            "property_type": prop.property_type,
            "price_from": float(min_price) if min_price is not None else None,
            "address": prop.address,
            "stop_index": stop.stop_index,
            "visit_status": stop.status,
        })

    return {"properties": comparisons}
