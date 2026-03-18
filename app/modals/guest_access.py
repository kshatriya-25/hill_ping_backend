# HillPing — Guest Access Code & Visit Card models (V2)

import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, Text,
    ForeignKey, DateTime, Index, JSON,
)
from sqlalchemy.orm import relationship
from ..database.base_class import Base


class GuestAccessCode(Base):
    __tablename__ = "guest_access_codes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    phone = Column(String(15), nullable=False, index=True)

    code_hash = Column(String(255), nullable=False)  # Argon2 hash of 6-digit code
    auth_token_hash = Column(String(255), nullable=True, unique=True)  # SHA-256 of auto-login URL token

    is_active = Column(Boolean, default=True, nullable=False)
    failed_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)

    created_by_mediator_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    converted_to_password = Column(Boolean, default=False, nullable=False)

    user = relationship("User", foreign_keys=[user_id])


class VisitCard(Base):
    __tablename__ = "visit_cards"

    id = Column(Integer, primary_key=True, index=True)
    card_ref = Column(String(20), nullable=False, unique=True, index=True)  # V-XXXXXX

    mediator_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    guest_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    guest_phone = Column(String(15), nullable=False)
    guest_name = Column(String(100), nullable=False)
    guest_count = Column(Integer, nullable=False, default=1)

    # Tour/visit link
    tour_session_id = Column(Integer, ForeignKey("tour_sessions.id", ondelete="SET NULL"), nullable=True)

    # Status
    status = Column(String(30), nullable=False, default="active")
    # active, touring, choice_made, booked, expired, abandoned

    guest_choice_property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)
    guest_choice_at = Column(DateTime(timezone=True), nullable=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True)

    # Tracking
    sms_sent_at = Column(DateTime(timezone=True), nullable=True)
    card_opened_at = Column(DateTime(timezone=True), nullable=True)
    card_open_count = Column(Integer, default=0, nullable=False)
    guest_browsed_properties = Column(Boolean, default=False, nullable=False)
    guest_search_count = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)

    mediator = relationship("User", foreign_keys=[mediator_id])
    guest = relationship("User", foreign_keys=[guest_id])
