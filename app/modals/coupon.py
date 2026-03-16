# HillPing — Coupon & CouponUsage models

import datetime
from sqlalchemy import (
    Column, Integer, String, Numeric, Boolean, ForeignKey,
    DateTime, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from ..database.base_class import Base


class Coupon(Base):
    __tablename__ = "coupons"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), nullable=False, unique=True, index=True)
    discount_type = Column(String(20), nullable=False)  # percentage, flat
    value = Column(Numeric(10, 2), nullable=False)
    max_cap = Column(Numeric(10, 2), nullable=True)  # max discount for percentage type
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_to = Column(DateTime(timezone=True), nullable=False)
    max_uses = Column(Integer, nullable=True)  # null = unlimited
    current_uses = Column(Integer, default=0, nullable=False)
    per_user_limit = Column(Integer, default=1, nullable=False)
    min_booking_amount = Column(Numeric(10, 2), nullable=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=True)  # null = platform-wide
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))

    property = relationship("Property")
    creator = relationship("User")
    usages = relationship("CouponUsage", back_populates="coupon", cascade="all, delete-orphan")


class CouponUsage(Base):
    __tablename__ = "coupon_usages"

    id = Column(Integer, primary_key=True, index=True)
    coupon_id = Column(Integer, ForeignKey("coupons.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True)
    discount_applied = Column(Numeric(10, 2), nullable=False)
    used_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))

    coupon = relationship("Coupon", back_populates="usages")
    user = relationship("User")

    __table_args__ = (
        Index("ix_coupon_usage_user_coupon", "user_id", "coupon_id"),
    )
