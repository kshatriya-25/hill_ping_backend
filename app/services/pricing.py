# HillPing — Pricing Calculation Service

import datetime
from decimal import Decimal
from sqlalchemy.orm import Session

from ..modals.property import Room
from ..core.config import settings


def calculate_booking_price(
    room: Room,
    check_in: datetime.date,
    check_out: datetime.date,
) -> dict:
    """
    Calculate the total price for a stay.

    Weekday = Mon-Thu, Weekend = Fri-Sun.
    Returns dict with: base_amount, service_fee, total_amount, nights, breakdown
    """
    nights = (check_out - check_in).days
    if nights <= 0:
        raise ValueError("Check-out must be after check-in")

    breakdown = []
    total = Decimal("0")

    current = check_in
    for _ in range(nights):
        is_weekend = current.weekday() >= 4  # Fri=4, Sat=5, Sun=6
        price = room.price_weekend if is_weekend else room.price_weekday
        day_type = "weekend" if is_weekend else "weekday"
        breakdown.append({
            "date": str(current),
            "type": day_type,
            "price": price,
        })
        total += price
        current += datetime.timedelta(days=1)

    commission_rate = Decimal(str(settings.COMMISSION_PERCENTAGE)) / Decimal("100")
    service_fee = (total * commission_rate).quantize(Decimal("0.01"))

    return {
        "base_amount": total,
        "service_fee": service_fee,
        "total_amount": total + service_fee,
        "nights": nights,
        "breakdown": breakdown,
    }
