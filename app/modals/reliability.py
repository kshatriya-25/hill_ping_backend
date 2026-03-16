# HillPing — Owner Reliability Score & Penalty models

import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from ..database.base_class import Base


class OwnerReliabilityScore(Base):
    __tablename__ = "owner_reliability_scores"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    # Individual metrics (0-100 each)
    acceptance_rate = Column(Float, default=100.0, nullable=False)
    avg_response_time = Column(Float, default=100.0, nullable=False)  # normalized: 0s=100, 30s=0
    cancellation_rate = Column(Float, default=100.0, nullable=False)  # inverted: 0 cancels = 100
    status_accuracy = Column(Float, default=100.0, nullable=False)    # inverted: 0 misses = 100

    # Weighted total (0-100)
    total_score = Column(Float, default=100.0, nullable=False)
    score_tier = Column(String(30), default="reliable", nullable=False)  # reliable, good, needs_improvement, at_risk

    # Raw counts for transparency
    total_pings = Column(Integer, default=0, nullable=False)
    accepted_pings = Column(Integer, default=0, nullable=False)
    rejected_pings = Column(Integer, default=0, nullable=False)
    expired_pings = Column(Integer, default=0, nullable=False)
    total_bookings = Column(Integer, default=0, nullable=False)
    cancelled_bookings = Column(Integer, default=0, nullable=False)

    # Suspension tracking
    consecutive_low_weeks = Column(Integer, default=0, nullable=False)
    is_suspended = Column(Boolean, default=False, nullable=False)
    suspended_until = Column(DateTime(timezone=True), nullable=True)

    calculated_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    owner = relationship("User", backref="reliability_score")


class OwnerPenalty(Base):
    __tablename__ = "owner_penalties"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    penalty_type = Column(String(30), nullable=False)  # warning, rank_drop, suspension, delist
    reason = Column(Text, nullable=False)
    issued_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    owner = relationship("User", backref="penalties")
