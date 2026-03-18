# HillPing — Mediator Commission Service (V2)

import datetime
import logging
from decimal import Decimal
from datetime import timezone

from sqlalchemy.orm import Session

from ..modals.mediator_commission import MediatorCommission, GuestAcquisition
from ..modals.booking import Booking

logger = logging.getLogger(__name__)


def calculate_booking_commission(booking: Booking, mediator_id: int, db: Session) -> MediatorCommission | None:
    """
    Calculate mediator commission for a booking.
    Tiered rates from PRD:
    - Up to ₹1,000 → ₹50 flat
    - ₹1,001 - ₹3,000 → 5%
    - ₹3,001 - ₹10,000 → 6%
    - Above ₹10,000 → 7%
    """
    amount = float(booking.total_amount)

    if amount <= 1000:
        commission_amount = Decimal("50")
        rate = round(50 / max(amount, 1) * 100, 2)
    elif amount <= 3000:
        rate = 5.0
        commission_amount = Decimal(str(round(amount * 0.05, 2)))
    elif amount <= 10000:
        rate = 6.0
        commission_amount = Decimal(str(round(amount * 0.06, 2)))
    else:
        rate = 7.0
        commission_amount = Decimal(str(round(amount * 0.07, 2)))

    commission = MediatorCommission(
        mediator_id=mediator_id,
        booking_id=booking.id,
        guest_id=booking.guest_id,
        commission_type="booking",
        booking_amount=booking.total_amount,
        commission_rate=rate,
        commission_amount=commission_amount,
        status="pending",
    )
    db.add(commission)
    db.commit()
    db.refresh(commission)

    logger.info(
        "Commission ₹%s (%.1f%%) for mediator %d on booking %s",
        commission_amount, rate, mediator_id, booking.booking_ref,
    )
    return commission


def check_residual_commission(booking: Booking, db: Session) -> MediatorCommission | None:
    """
    If the guest was acquired by a mediator within 12 months,
    create a residual commission (1% of booking).
    """
    acquisition = db.query(GuestAcquisition).filter(
        GuestAcquisition.guest_id == booking.guest_id,
        GuestAcquisition.is_active == True,
        GuestAcquisition.residual_commission_until > datetime.datetime.now(timezone.utc),
    ).first()

    if not acquisition:
        return None

    # Don't create residual if mediator is the one who booked (they get full commission)
    if booking.mediator_id == acquisition.mediator_id:
        return None

    amount = float(booking.total_amount)
    residual_amount = Decimal(str(round(amount * 0.01, 2)))

    commission = MediatorCommission(
        mediator_id=acquisition.mediator_id,
        booking_id=booking.id,
        guest_id=booking.guest_id,
        commission_type="residual",
        booking_amount=booking.total_amount,
        commission_rate=1.0,
        commission_amount=residual_amount,
        status="pending",
    )
    db.add(commission)

    acquisition.total_residual_earned += residual_amount
    db.commit()
    db.refresh(commission)

    logger.info(
        "Residual commission ₹%s for mediator %d (acquired guest %d)",
        residual_amount, acquisition.mediator_id, booking.guest_id,
    )
    return commission


def record_guest_acquisition(mediator_id: int, guest_id: int, booking_id: int, db: Session) -> GuestAcquisition:
    """Record that a mediator acquired a guest (for residual commissions)."""
    existing = db.query(GuestAcquisition).filter(
        GuestAcquisition.guest_id == guest_id,
    ).first()

    if existing:
        return existing  # Already acquired by someone

    residual_until = datetime.datetime.now(timezone.utc) + datetime.timedelta(
        days=30 * 12  # ~12 months
    )

    acquisition = GuestAcquisition(
        mediator_id=mediator_id,
        guest_id=guest_id,
        first_booking_id=booking_id,
        residual_commission_until=residual_until,
    )
    db.add(acquisition)
    db.commit()
    db.refresh(acquisition)

    logger.info("Guest %d acquired by mediator %d", guest_id, mediator_id)
    return acquisition
