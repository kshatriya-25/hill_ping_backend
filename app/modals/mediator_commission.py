# HillPing — Mediator Commission & Guest Acquisition models (V2)

import datetime
from sqlalchemy import (
    Column, Integer, String, Numeric, Boolean,
    ForeignKey, DateTime, Index, Float,
)
from sqlalchemy.orm import relationship
from ..database.base_class import Base


class MediatorCommission(Base):
    __tablename__ = "mediator_commissions"

    id = Column(Integer, primary_key=True, index=True)
    mediator_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True)
    guest_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    commission_type = Column(String(20), nullable=False)
    # booking, residual, bonus, referral

    booking_amount = Column(Numeric(10, 2), nullable=False)
    commission_rate = Column(Float, nullable=False)  # percentage
    commission_amount = Column(Numeric(10, 2), nullable=False)

    status = Column(String(20), nullable=False, default="pending")
    # pending, approved, paid, disputed, cancelled

    payout_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))

    mediator = relationship("User", foreign_keys=[mediator_id])
    booking = relationship("Booking")

    __table_args__ = (
        Index("ix_mediator_commissions_type_status", "commission_type", "status"),
    )


class GuestAcquisition(Base):
    __tablename__ = "guest_acquisitions"

    id = Column(Integer, primary_key=True, index=True)
    mediator_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    guest_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    first_booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True)

    acquired_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    residual_commission_until = Column(DateTime(timezone=True), nullable=False)  # acquired_at + 12 months
    is_active = Column(Boolean, default=True, nullable=False)
    total_residual_earned = Column(Numeric(10, 2), default=0, nullable=False)

    mediator = relationship("User", foreign_keys=[mediator_id])
    guest = relationship("User", foreign_keys=[guest_id])
