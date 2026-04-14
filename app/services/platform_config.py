# HillPing — Platform Config Service
#
# Reads admin-tunable settings from the platform_config DB table.
# Falls back to env/defaults from config.py if a key is not set in DB.
#
# Configurable keys (with defaults):
#
# RELIABILITY
#   weight_acceptance          0.40    — weight for acceptance rate
#   weight_response_time       0.30    — weight for response time score
#   weight_cancellation        0.20    — weight for cancellation score
#   weight_status_accuracy     0.10    — weight for status accuracy
#   response_time_max_seconds  30      — the "worst" response time (scores 0)
#   instant_confirm_threshold  95      — min acceptance rate for instant confirm
#   low_score_threshold        50      — below this = "at_risk"
#   low_score_delist_weeks     2       — consecutive weeks below threshold before delist
#
# PENALTIES
#   missed_pings_warning       3       — missed pings per week to trigger warning
#   rejections_rank_drop       5       — rejections per month to trigger rank drop
#   cancellations_suspension   2       — cancellations per month to trigger suspension
#   suspension_days            7       — how many days a suspension lasts
#
# PLATFORM
#   ping_ttl_seconds           30      — how long an owner has to respond
#   commission_percentage      10      — platform fee %
#   min_booking_amount         1       — minimum booking amount (INR)

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..core.config import settings
from ..modals.platform_config import PlatformConfig

# Keys whose values are stored as JSON arrays (not plain strings)
LIST_KEYS = {"room_types_list", "property_types_list"}

logger = logging.getLogger(__name__)

# In-memory cache to avoid DB reads on every request
_cache: dict[str, str] = {}
_cache_loaded = False


# ── Defaults (match the hardcoded values before this change) ──────────────────

DEFAULTS = {
    # Reliability weights
    "weight_acceptance": "0.40",
    "weight_response_time": "0.30",
    "weight_cancellation": "0.20",
    "weight_status_accuracy": "0.10",

    # Response time scoring
    "response_time_max_seconds": str(settings.PING_TTL_SECONDS),

    # Score tiers & thresholds
    "instant_confirm_threshold": str(settings.INSTANT_CONFIRM_THRESHOLD),
    "low_score_threshold": "50",
    "low_score_delist_weeks": "2",

    # Penalty thresholds
    "missed_pings_warning": "3",
    "rejections_rank_drop": "5",
    "cancellations_suspension": "2",
    "suspension_days": "7",

    # Platform settings
    "ping_ttl_seconds": str(settings.PING_TTL_SECONDS),
    "commission_percentage": str(settings.COMMISSION_PERCENTAGE),
    "min_booking_amount": "1",

    # Crudable list settings (stored as JSON arrays)
    "room_types_list": json.dumps(["single", "double", "dormitory", "suite"]),
    "property_types_list": json.dumps(["homestay", "hotel", "cottage", "villa"]),

    # V2: Mediator reliability weights
    "mediator_weight_completion": "0.35",
    "mediator_weight_satisfaction": "0.30",
    "mediator_weight_speed": "0.20",
    "mediator_weight_accuracy": "0.15",

    # V2: Mediator commission settings
    "mediator_commission_tier1_flat": "50",      # ₹50 flat for bookings ≤ ₹1000
    "mediator_commission_tier2_rate": "5",       # 5% for ₹1001-3000
    "mediator_commission_tier3_rate": "6",       # 6% for ₹3001-10000
    "mediator_commission_tier4_rate": "7",       # 7% for >₹10000
    "residual_commission_rate": "1",             # 1% residual for acquired guests
    "residual_commission_months": str(settings.RESIDUAL_COMMISSION_MONTHS),
}

# Human-readable descriptions for admin UI
DESCRIPTIONS = {
    "weight_acceptance": "Weight for acceptance rate in reliability score (0-1, all weights must sum to 1)",
    "weight_response_time": "Weight for response time in reliability score (0-1)",
    "weight_cancellation": "Weight for cancellation rate in reliability score (0-1)",
    "weight_status_accuracy": "Weight for status accuracy in reliability score (0-1)",
    "response_time_max_seconds": "Response time that scores 0 (worst). Owner responding in 0s scores 100, this value scores 0.",
    "instant_confirm_threshold": "Minimum acceptance rate (%) for auto-confirming bookings without ping",
    "low_score_threshold": "Score below this marks owner as 'at_risk'",
    "low_score_delist_weeks": "Consecutive weeks below low_score_threshold before delisting",
    "missed_pings_warning": "Missed pings per week before issuing a warning penalty",
    "rejections_rank_drop": "Rejections per month before issuing a rank drop penalty",
    "cancellations_suspension": "Cancellations (after acceptance) per month before suspending",
    "suspension_days": "Number of days a suspension lasts",
    "ping_ttl_seconds": "How many seconds the owner has to respond to a ping",
    "commission_percentage": "Platform commission percentage on each booking",
    "min_booking_amount": "Minimum booking amount in INR",
    "mediator_weight_completion": "Weight for booking completion rate in mediator reliability (0-1)",
    "mediator_weight_satisfaction": "Weight for guest satisfaction in mediator reliability (0-1)",
    "mediator_weight_speed": "Weight for response speed in mediator reliability (0-1)",
    "mediator_weight_accuracy": "Weight for booking accuracy in mediator reliability (0-1)",
    "mediator_commission_tier1_flat": "Flat commission (₹) for bookings ≤ ₹1000",
    "mediator_commission_tier2_rate": "Commission % for bookings ₹1001-3000",
    "mediator_commission_tier3_rate": "Commission % for bookings ₹3001-10000",
    "mediator_commission_tier4_rate": "Commission % for bookings > ₹10000",
    "residual_commission_rate": "Residual commission % for acquired guests on subsequent bookings",
    "residual_commission_months": "Months of residual commission eligibility after guest acquisition",
    "room_types_list": "List of available room types (JSON array of strings)",
    "property_types_list": "List of available property types (JSON array of strings)",
}


def load_config_cache(db: Session) -> None:
    """Load all platform config from DB into memory cache."""
    global _cache, _cache_loaded
    rows = db.query(PlatformConfig).all()
    _cache = {row.key: row.value for row in rows}
    _cache_loaded = True
    logger.info("Platform config cache loaded: %d keys", len(_cache))


def get_config(key: str, db: Optional[Session] = None) -> str:
    """
    Get a config value. Priority: DB cache → defaults.
    If DB cache is not loaded and db session is provided, loads it.
    """
    global _cache_loaded
    if not _cache_loaded and db is not None:
        load_config_cache(db)

    return _cache.get(key, DEFAULTS.get(key, ""))


def get_config_float(key: str, db: Optional[Session] = None) -> float:
    return float(get_config(key, db) or "0")


def get_config_int(key: str, db: Optional[Session] = None) -> int:
    return int(float(get_config(key, db) or "0"))


def set_config(key: str, value: str, db: Session) -> PlatformConfig:
    """Set a config value (upsert)."""
    record = db.query(PlatformConfig).filter(PlatformConfig.key == key).first()
    if record:
        record.value = value
    else:
        record = PlatformConfig(
            key=key,
            value=value,
            description=DESCRIPTIONS.get(key),
        )
        db.add(record)

    db.commit()
    db.refresh(record)

    # Update cache
    _cache[key] = value
    logger.info("Platform config updated: %s = %s", key, value)

    return record


def get_all_config(db: Session) -> dict:
    """Get all config with current values (DB overrides + defaults for unset keys)."""
    if not _cache_loaded:
        load_config_cache(db)

    result = {}
    for key, default in DEFAULTS.items():
        raw = _cache.get(key, default)
        if key in LIST_KEYS:
            try:
                value = json.loads(raw)
            except (ValueError, TypeError):
                value = json.loads(default)
        else:
            value = raw
        result[key] = {
            "value": value,
            "default": json.loads(default) if key in LIST_KEYS else default,
            "is_custom": key in _cache,
            "description": DESCRIPTIONS.get(key, ""),
        }
    return result


def reset_config(key: str, db: Session) -> None:
    """Reset a config key to its default (remove from DB)."""
    record = db.query(PlatformConfig).filter(PlatformConfig.key == key).first()
    if record:
        db.delete(record)
        db.commit()
    _cache.pop(key, None)
    logger.info("Platform config reset to default: %s", key)
