# HillPing — Reliability Score & Penalty schemas

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ReliabilityScoreResponse(BaseModel):
    id: int
    owner_id: int
    acceptance_rate: float
    avg_response_time: float
    cancellation_rate: float
    status_accuracy: float
    total_score: float
    score_tier: str
    total_pings: int
    accepted_pings: int
    rejected_pings: int
    expired_pings: int
    total_bookings: int
    cancelled_bookings: int
    consecutive_low_weeks: int
    is_suspended: bool
    suspended_until: Optional[datetime] = None
    calculated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PenaltyResponse(BaseModel):
    id: int
    owner_id: int
    penalty_type: str
    reason: str
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool

    model_config = {"from_attributes": True}


class ScoreSummary(BaseModel):
    """Lightweight score for embedding in property responses."""
    total_score: float
    score_tier: str
    is_instant_confirm: bool
    acceptance_rate: float
