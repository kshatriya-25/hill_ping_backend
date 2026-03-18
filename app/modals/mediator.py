# HillPing — Mediator Profile & Reliability models (V2)

import datetime
from sqlalchemy import (
    Column, Integer, String, Numeric, Boolean, Text, Float,
    ForeignKey, DateTime, Index, JSON,
)
from sqlalchemy.orm import relationship
from ..database.base_class import Base


class MediatorProfile(Base):
    __tablename__ = "mediator_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    # KYC
    aadhaar_number_hash = Column(String(255), nullable=True)  # SHA-256 hashed
    aadhaar_doc_url = Column(String(500), nullable=True)
    profile_photo_url = Column(String(500), nullable=True)

    # Type & zone
    mediator_type = Column(
        String(30), nullable=False, default="freelance_agent",
    )  # auto_driver, travel_desk, local_guide, shop_owner, freelance_agent, hotel_front_desk

    operating_zone = Column(JSON, nullable=True)
    # Array of { "label": "Bus Stand", "lat": 11.77, "lng": 78.21, "radius_km": 2 }

    # Verification
    verification_status = Column(String(20), nullable=False, default="pending")  # pending, verified, rejected
    verification_note = Column(Text, nullable=True)  # rejection reason or admin notes
    verified_at = Column(DateTime(timezone=True), nullable=True)
    verified_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    badge_issued = Column(Boolean, default=False, nullable=False)

    # Wallet
    wallet_balance = Column(Numeric(10, 2), nullable=False, default=0)

    # Stats (denormalized for dashboard speed)
    total_bookings = Column(Integer, nullable=False, default=0)
    total_earnings = Column(Numeric(10, 2), nullable=False, default=0)
    acquired_guests_count = Column(Integer, nullable=False, default=0)

    # Referral
    referral_code = Column(String(20), nullable=False, unique=True, index=True)
    referred_by = Column(Integer, ForeignKey("mediator_profiles.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_mediator_profiles_type_status", "mediator_type", "verification_status"),
    )


class MediatorWalletTransaction(Base):
    __tablename__ = "mediator_wallet_transactions"

    id = Column(Integer, primary_key=True, index=True)
    mediator_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    type = Column(String(20), nullable=False)  # topup, debit, credit, refund
    amount = Column(Numeric(10, 2), nullable=False)
    balance_after = Column(Numeric(10, 2), nullable=False)
    reference = Column(String(100), nullable=True)  # booking_ref or razorpay_payment_id
    description = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


class MediatorReliabilityScore(Base):
    __tablename__ = "mediator_reliability_scores"

    id = Column(Integer, primary_key=True, index=True)
    mediator_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    # Component scores (0-100)
    completion_rate = Column(Float, nullable=False, default=100.0)
    guest_satisfaction = Column(Float, nullable=False, default=100.0)
    response_speed = Column(Float, nullable=False, default=100.0)
    accuracy = Column(Float, nullable=False, default=100.0)

    # Weighted total
    total_score = Column(Float, nullable=False, default=100.0)
    score_tier = Column(String(30), nullable=False, default="trusted")
    # star, trusted, needs_improvement, at_risk

    # Raw counts
    total_bookings = Column(Integer, nullable=False, default=0)
    completed_bookings = Column(Integer, nullable=False, default=0)
    cancelled_bookings = Column(Integer, nullable=False, default=0)
    disputed_bookings = Column(Integer, nullable=False, default=0)
    total_visits = Column(Integer, nullable=False, default=0)
    no_show_visits = Column(Integer, nullable=False, default=0)

    # Suspension
    is_suspended = Column(Boolean, default=False, nullable=False)
    suspended_until = Column(DateTime(timezone=True), nullable=True)

    calculated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )


class MediatorPenalty(Base):
    __tablename__ = "mediator_penalties"

    id = Column(Integer, primary_key=True, index=True)
    mediator_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    penalty_type = Column(String(30), nullable=False)  # warning, rank_drop, suspension, delist
    reason = Column(Text, nullable=False)
    issued_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
