# HillPing — Trip Card Service (V2)

import datetime
import logging
import secrets
import string
from datetime import timezone

from sqlalchemy.orm import Session

from ..modals.trip_card import TripCard
from ..modals.booking import Booking

logger = logging.getLogger(__name__)


class TripCardError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code


def _generate_card_ref() -> str:
    chars = string.ascii_uppercase + string.digits
    return "HP-" + "".join(secrets.choice(chars) for _ in range(6))


def create_trip_card(booking_id: int, db: Session) -> TripCard:
    """Auto-create a trip card when a booking is confirmed."""
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise TripCardError("Booking not found", 404)

    # Check if trip card already exists
    existing = db.query(TripCard).filter(TripCard.booking_id == booking_id).first()
    if existing:
        return existing

    card_ref = _generate_card_ref()
    while db.query(TripCard).filter(TripCard.card_ref == card_ref).first():
        card_ref = _generate_card_ref()

    card = TripCard(
        card_ref=card_ref,
        booking_id=booking_id,
        guest_id=booking.guest_id,
        mediator_id=booking.mediator_id,
        property_id=booking.property_id,
        owner_id=booking.owner_id,
        status="created",
    )
    db.add(card)
    db.commit()
    db.refresh(card)

    logger.info("Trip card %s created for booking %s", card_ref, booking.booking_ref)
    return card


def update_en_route(card_ref: str, latitude: float | None, longitude: float | None, eta_minutes: int | None, db: Session) -> TripCard:
    """Guest taps 'I'm on my way'."""
    card = _get_card(card_ref, db)

    if card.status not in ("created", "en_route"):
        raise TripCardError(f"Cannot update — trip is {card.status}")

    card.status = "en_route"
    if latitude and longitude:
        card.guest_latitude = latitude
        card.guest_longitude = longitude
        card.last_location_update = datetime.datetime.now(timezone.utc)
    if eta_minutes:
        card.estimated_arrival_minutes = eta_minutes

    card.owner_notified_en_route = True
    db.commit()
    db.refresh(card)

    return card


def mark_arrived(card_ref: str, db: Session) -> TripCard:
    """Guest arrived at property (proximity or manual)."""
    card = _get_card(card_ref, db)

    if card.status not in ("created", "en_route"):
        raise TripCardError(f"Cannot mark arrived — trip is {card.status}")

    card.status = "arrived"
    card.owner_notified_arrival = True
    db.commit()
    db.refresh(card)

    return card


def check_in(card_ref: str, owner_id: int, db: Session) -> TripCard:
    """Owner confirms guest check-in."""
    card = _get_card(card_ref, db)

    if card.owner_id != owner_id:
        raise TripCardError("Not authorized", 403)
    if card.status not in ("created", "en_route", "arrived"):
        raise TripCardError(f"Cannot check in — trip is {card.status}")

    card.status = "checked_in"
    card.check_in_time = datetime.datetime.now(timezone.utc)
    db.commit()
    db.refresh(card)

    return card


def complete_trip(card_ref: str, owner_id: int, db: Session) -> TripCard:
    """Owner marks checkout."""
    card = _get_card(card_ref, db)

    if card.owner_id != owner_id:
        raise TripCardError("Not authorized", 403)
    if card.status != "checked_in":
        raise TripCardError(f"Cannot complete — trip is {card.status}")

    card.status = "completed"
    card.check_out_time = datetime.datetime.now(timezone.utc)
    db.commit()
    db.refresh(card)

    return card


def cancel_trip(card_ref: str, db: Session) -> TripCard:
    """Guest cancels trip."""
    card = _get_card(card_ref, db)

    if card.status in ("completed", "cancelled"):
        raise TripCardError(f"Cannot cancel — trip is {card.status}")

    card.status = "cancelled"
    db.commit()
    db.refresh(card)

    return card


def rate_stay(card_ref: str, rating: int, comment: str | None, db: Session) -> TripCard:
    """Guest rates the property stay."""
    card = _get_card(card_ref, db)

    if card.status != "completed":
        raise TripCardError("Can only rate after checkout")
    if not 1 <= rating <= 5:
        raise TripCardError("Rating must be 1-5")

    card.guest_rating_stay = rating
    card.rating_comment = comment
    db.commit()
    db.refresh(card)

    return card


def rate_mediator(card_ref: str, rating: int, db: Session) -> TripCard:
    """Guest rates the mediator."""
    card = _get_card(card_ref, db)

    if card.status != "completed":
        raise TripCardError("Can only rate after checkout")
    if not 1 <= rating <= 5:
        raise TripCardError("Rating must be 1-5")

    card.guest_rating_mediator = rating
    db.commit()
    db.refresh(card)

    return card


def _get_card(card_ref: str, db: Session) -> TripCard:
    card = db.query(TripCard).filter(TripCard.card_ref == card_ref).first()
    if not card:
        raise TripCardError("Trip card not found", 404)
    return card
