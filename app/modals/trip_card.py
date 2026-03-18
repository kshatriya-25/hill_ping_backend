# HillPing — Trip Card model (V2)

import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text,
    ForeignKey, DateTime, Boolean, Index,
)
from sqlalchemy.orm import relationship
from ..database.base_class import Base


class TripCard(Base):
    __tablename__ = "trip_cards"

    id = Column(Integer, primary_key=True, index=True)
    card_ref = Column(String(20), nullable=False, unique=True, index=True)  # HP-XXXXXX

    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, unique=True)
    guest_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    mediator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Status: created → en_route → arrived → checked_in → completed / cancelled
    status = Column(String(20), nullable=False, default="created")

    # Guest location
    guest_latitude = Column(Float, nullable=True)
    guest_longitude = Column(Float, nullable=True)
    last_location_update = Column(DateTime(timezone=True), nullable=True)

    # Timing
    estimated_arrival_minutes = Column(Integer, nullable=True)
    check_in_time = Column(DateTime(timezone=True), nullable=True)
    check_out_time = Column(DateTime(timezone=True), nullable=True)

    # Check-in details
    check_in_instructions = Column(Text, nullable=True)
    access_code = Column(String(20), nullable=True)  # Smart lock code

    # Notifications
    owner_notified_en_route = Column(Boolean, default=False, nullable=False)
    owner_notified_arrival = Column(Boolean, default=False, nullable=False)

    # Ratings
    guest_rating_stay = Column(Integer, nullable=True)  # 1-5
    guest_rating_mediator = Column(Integer, nullable=True)  # 1-5
    rating_comment = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    booking = relationship("Booking")
    guest = relationship("User", foreign_keys=[guest_id])
    mediator = relationship("User", foreign_keys=[mediator_id])
    property = relationship("Property")
    owner = relationship("User", foreign_keys=[owner_id])
