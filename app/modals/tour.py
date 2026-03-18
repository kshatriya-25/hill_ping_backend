# HillPing — Tour Session models (V2)

import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey,
    DateTime, Index,
)
from sqlalchemy.orm import relationship
from ..database.base_class import Base


class TourSession(Base):
    __tablename__ = "tour_sessions"

    id = Column(Integer, primary_key=True, index=True)
    tour_ref = Column(String(20), nullable=False, unique=True, index=True)  # T-XXXXXX

    mediator_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    guest_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    status = Column(String(20), nullable=False, default="active")  # active, completed, abandoned, expired

    total_stops = Column(Integer, nullable=False, default=1)
    current_stop_index = Column(Integer, nullable=False, default=0)

    started_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    extended = Column(Boolean, default=False, nullable=False)

    completed_at = Column(DateTime(timezone=True), nullable=True)
    booked_property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))

    # Relationships
    mediator = relationship("User", foreign_keys=[mediator_id])
    guest = relationship("User", foreign_keys=[guest_id])
    stops = relationship("TourStop", back_populates="tour", order_by="TourStop.stop_index")


class TourStop(Base):
    __tablename__ = "tour_stops"

    id = Column(Integer, primary_key=True, index=True)
    tour_id = Column(Integer, ForeignKey("tour_sessions.id", ondelete="CASCADE"), nullable=False, index=True)

    stop_index = Column(Integer, nullable=False)
    visit_request_id = Column(Integer, ForeignKey("visit_requests.id", ondelete="SET NULL"), nullable=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)

    status = Column(String(20), nullable=False, default="pending")  # pending, active, booked, passed, skipped

    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    tour = relationship("TourSession", back_populates="stops")
    visit_request = relationship("VisitRequest")
    property = relationship("Property")

    __table_args__ = (
        Index("ix_tour_stops_tour_status", "tour_id", "status"),
    )
