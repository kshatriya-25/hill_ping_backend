# HillPing — Pricing Calculation Service

import datetime
import math
from decimal import Decimal

from ..modals.property import Room
from ..core.config import settings

_DAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _day_label(d: datetime.date) -> str:
    return _DAY_LABELS[d.weekday()]


def room_flat_extras_per_night(room: Room) -> Decimal:
    mc = getattr(room, "mediator_commission", None)
    pf = getattr(room, "platform_fee", None)
    d_mc = Decimal(str(mc)) if mc is not None else Decimal("0")
    d_pf = Decimal(str(pf)) if pf is not None else Decimal("0")
    return d_mc + d_pf


def room_min_guest_nightly(room: Room) -> Decimal:
    """Lowest guest-facing nightly rate (owner rack + flat fees) for this room."""
    extras = room_flat_extras_per_night(room)
    wd = Decimal(str(room.price_weekday)) + extras
    we = Decimal(str(room.price_weekend)) + extras
    return min(wd, we)


def mediator_listing_fee_per_night(rooms: list[Room], price_min_guest: Decimal | None) -> float | None:
    """
    Flat mediator ₹/night from room rows for mediator search / "Your cut".

    Prefer rooms whose guest nightly floor matches the property's displayed price_min
    (within ₹0.50 for rounding). Otherwise use the maximum configured fee across rooms.
    """
    if not rooms:
        return None
    fees: list[float] = []
    for r in rooms:
        mc = getattr(r, "mediator_commission", None)
        if mc is not None:
            fees.append(float(mc))
    if not fees:
        return None
    if price_min_guest is None:
        return max(fees)
    min_g = float(price_min_guest)
    tied: list[float] = []
    for r in rooms:
        mc = getattr(r, "mediator_commission", None)
        if mc is None:
            continue
        rv = float(room_min_guest_nightly(r))
        if math.isclose(rv, min_g, rel_tol=0.0, abs_tol=0.51):
            tied.append(float(mc))
    if tied:
        return max(tied)
    return max(fees)


def _is_room_weekend(room: Room, d: datetime.date) -> bool:
    labels = getattr(room, "weekend_days", None)
    if not labels:
        return d.weekday() >= 4
    return _day_label(d) in set(labels)


def calculate_booking_price(
    room: Room,
    check_in: datetime.date,
    check_out: datetime.date,
    commission_override: float = None,
    commission_type: str = "percentage",
) -> dict:
    """
    Calculate the total price for a stay.

    Uses room.weekend_days (Mon..Sun labels) when set; otherwise Fri–Sun are weekends.
    Each guest night = owner rack + mediator_commission + platform_fee (flat per night).
    Service fee (platform %) applies to owner rack subtotal only.

    Returns dict with: base_amount, service_fee, total_amount, nights, breakdown
    """
    nights = (check_out - check_in).days
    if nights <= 0:
        raise ValueError("Check-out must be after check-in")

    extras = room_flat_extras_per_night(room)
    breakdown = []
    owner_subtotal = Decimal("0")

    current = check_in
    for _ in range(nights):
        is_weekend = _is_room_weekend(room, current)
        owner_price = room.price_weekend if is_weekend else room.price_weekday
        owner_dec = Decimal(str(owner_price))
        night_guest = owner_dec + extras
        day_type = "weekend" if is_weekend else "weekday"
        breakdown.append({
            "date": str(current),
            "type": day_type,
            "price": night_guest,
            "owner_price": owner_dec,
            "extras": extras,
        })
        owner_subtotal += owner_dec
        current += datetime.timedelta(days=1)

    guest_subtotal = owner_subtotal + extras * Decimal(nights)

    if commission_override is not None and commission_type == "fixed":
        service_fee = Decimal(str(commission_override)).quantize(Decimal("0.01"))
    else:
        pct = commission_override if commission_override is not None else settings.COMMISSION_PERCENTAGE
        commission_rate = Decimal(str(pct)) / Decimal("100")
        service_fee = (owner_subtotal * commission_rate).quantize(Decimal("0.01"))

    return {
        "base_amount": guest_subtotal,
        "service_fee": service_fee,
        "total_amount": guest_subtotal + service_fee,
        "nights": nights,
        "breakdown": breakdown,
    }
