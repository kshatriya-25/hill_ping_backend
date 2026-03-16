# HillPing — Booking & Payout models

import datetime
from sqlalchemy import (
    Column, Integer, String, Numeric, Boolean, Text,
    ForeignKey, DateTime, Date, Index,
)
from sqlalchemy.orm import relationship
from ..database.base_class import Base


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    booking_ref = Column(String(20), nullable=False, unique=True, index=True)  # HP-XXXXXX
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)
    guest_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ping_session_id = Column(Integer, ForeignKey("ping_sessions.id", ondelete="SET NULL"), nullable=True)

    check_in = Column(Date, nullable=False)
    check_out = Column(Date, nullable=False)
    guests_count = Column(Integer, nullable=False, default=1)
    nights = Column(Integer, nullable=False, default=1)

    # Pricing
    base_amount = Column(Numeric(10, 2), nullable=False)
    discount_amount = Column(Numeric(10, 2), nullable=False, default=0)
    service_fee = Column(Numeric(10, 2), nullable=False, default=0)
    total_amount = Column(Numeric(10, 2), nullable=False)

    coupon_id = Column(Integer, nullable=True)  # FK added when coupon model exists

    # Status
    status = Column(String(30), nullable=False, default="pending")
    # pending, confirmed, cancelled_by_guest, cancelled_by_owner, completed, no_show

    # Payment
    razorpay_order_id = Column(String(100), nullable=True)
    razorpay_payment_id = Column(String(100), nullable=True)
    razorpay_signature = Column(String(255), nullable=True)
    payment_status = Column(String(20), nullable=False, default="pending")
    # pending, authorized, captured, refunded, failed

    # Cancellation
    cancellation_reason = Column(Text, nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    # Relationships
    property = relationship("Property")
    room = relationship("Room")
    guest = relationship("User", foreign_keys=[guest_id])
    owner = relationship("User", foreign_keys=[owner_id])
    ping_session = relationship("PingSession")

    __table_args__ = (
        Index("ix_bookings_guest_status", "guest_id", "status"),
        Index("ix_bookings_owner_status", "owner_id", "status"),
    )


class Payout(Base):
    __tablename__ = "payouts"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True)

    gross_amount = Column(Numeric(10, 2), nullable=False)
    commission_amount = Column(Numeric(10, 2), nullable=False)
    net_amount = Column(Numeric(10, 2), nullable=False)

    status = Column(String(20), nullable=False, default="pending")  # pending, processed, failed
    payout_date = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))

    owner = relationship("User")
    booking = relationship("Booking")
