# HillPing — Ping Session model (persistent audit trail in Postgres)

import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Numeric, ForeignKey,
    DateTime, Date, Index,
)
from sqlalchemy.orm import relationship
from ..database.base_class import Base


class PingSession(Base):
    __tablename__ = "ping_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(64), nullable=False, unique=True, index=True)  # UUID hex
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)
    guest_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    check_in = Column(Date, nullable=False)
    check_out = Column(Date, nullable=False)
    guests_count = Column(Integer, nullable=False, default=1)
    requested_amount = Column(Numeric(10, 2), nullable=True)

    status = Column(String(20), nullable=False, default="pending")  # pending, accepted, rejected, expired
    owner_response_time = Column(Float, nullable=True)  # seconds taken to respond

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    responded_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    property = relationship("Property")
    guest = relationship("User", foreign_keys=[guest_id])
    owner = relationship("User", foreign_keys=[owner_id])

    __table_args__ = (
        Index("ix_ping_sessions_owner_status", "owner_id", "status"),
        Index("ix_ping_sessions_owner_created", "owner_id", "created_at"),
    )
