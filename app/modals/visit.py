# HillPing — Visit Request model (V2)

import datetime
from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey,
    DateTime, Boolean, Index,
)
from sqlalchemy.orm import relationship
from ..database.base_class import Base


class VisitRequest(Base):
    __tablename__ = "visit_requests"

    id = Column(Integer, primary_key=True, index=True)
    visit_ref = Column(String(20), nullable=False, unique=True, index=True)  # V-XXXXXX

    mediator_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)
    guest_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ping_session_id = Column(Integer, ForeignKey("ping_sessions.id", ondelete="SET NULL"), nullable=True)

    # Tour link (nullable if standalone visit)
    tour_session_id = Column(Integer, ForeignKey("tour_sessions.id", ondelete="SET NULL"), nullable=True)
    tour_stop_order = Column(Integer, nullable=True)

    guest_count = Column(Integer, nullable=False, default=1)
    eta_minutes = Column(Integer, nullable=True)

    # Status flow: requested → en_route → arrived → booked / passed / expired / owner_released
    status = Column(String(20), nullable=False, default="requested")

    hold_expires_at = Column(DateTime(timezone=True), nullable=False)
    hold_extended = Column(Boolean, default=False, nullable=False)

    pass_reason = Column(Text, nullable=True)
    # "too_expensive", "room_quality", "location", "owner_unavailable", "guest_left", "other"

    arrived_at = Column(DateTime(timezone=True), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    # Relationships
    mediator = relationship("User", foreign_keys=[mediator_id])
    property = relationship("Property")
    room = relationship("Room")
    guest = relationship("User", foreign_keys=[guest_id])
    owner = relationship("User", foreign_keys=[owner_id])

    __table_args__ = (
        Index("ix_visit_requests_mediator_status", "mediator_id", "status"),
        Index("ix_visit_requests_property_status", "property_id", "status"),
    )
