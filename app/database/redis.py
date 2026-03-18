# HillPing — Redis client singleton

import json
import logging
from typing import Optional

import redis

from ..core.config import settings

logger = logging.getLogger(__name__)

redis_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    """Return the shared Redis client, creating it on first call."""
    global redis_client
    if redis_client is None:
        redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=5,
            retry_on_timeout=True,
        )
        logger.info("Redis client connected to %s:%s/%s", settings.REDIS_HOST, settings.REDIS_PORT, settings.REDIS_DB)
    return redis_client


# ── Ping session helpers ──────────────────────────────────────────────────────

PING_KEY_PREFIX = "ping:"


def store_ping_session(session_id: str, data: dict, ttl: int = None) -> None:
    """Store a ping session in Redis with TTL (default: PING_TTL_SECONDS)."""
    if ttl is None:
        ttl = settings.PING_TTL_SECONDS
    r = get_redis()
    r.setex(f"{PING_KEY_PREFIX}{session_id}", ttl, json.dumps(data))


def get_ping_session(session_id: str) -> Optional[dict]:
    """Retrieve a ping session from Redis. Returns None if expired/missing."""
    r = get_redis()
    raw = r.get(f"{PING_KEY_PREFIX}{session_id}")
    if raw is None:
        return None
    return json.loads(raw)


def delete_ping_session(session_id: str) -> None:
    """Remove a ping session from Redis."""
    r = get_redis()
    r.delete(f"{PING_KEY_PREFIX}{session_id}")


def get_ping_ttl(session_id: str) -> int:
    """Get remaining TTL in seconds for a ping session. Returns -2 if key doesn't exist."""
    r = get_redis()
    return r.ttl(f"{PING_KEY_PREFIX}{session_id}")


# ── Visit hold helpers (V2) ──────────────────────────────────────────────────

VISIT_KEY_PREFIX = "visit_hold:"


def store_visit_hold(visit_ref: str, data: dict, ttl: int = None) -> None:
    """Store a visit hold in Redis with TTL (default: VISIT_HOLD_TTL_SECONDS)."""
    if ttl is None:
        ttl = settings.VISIT_HOLD_TTL_SECONDS
    r = get_redis()
    r.setex(f"{VISIT_KEY_PREFIX}{visit_ref}", ttl, json.dumps(data))


def get_visit_hold(visit_ref: str) -> Optional[dict]:
    """Retrieve a visit hold from Redis. Returns None if expired/missing."""
    r = get_redis()
    raw = r.get(f"{VISIT_KEY_PREFIX}{visit_ref}")
    if raw is None:
        return None
    return json.loads(raw)


def delete_visit_hold(visit_ref: str) -> None:
    """Remove a visit hold from Redis."""
    r = get_redis()
    r.delete(f"{VISIT_KEY_PREFIX}{visit_ref}")


def get_visit_hold_ttl(visit_ref: str) -> int:
    """Get remaining TTL in seconds for a visit hold. Returns -2 if key doesn't exist."""
    r = get_redis()
    return r.ttl(f"{VISIT_KEY_PREFIX}{visit_ref}")


def extend_visit_hold(visit_ref: str, extra_seconds: int) -> bool:
    """Extend a visit hold TTL. Returns False if key doesn't exist."""
    r = get_redis()
    current_ttl = r.ttl(f"{VISIT_KEY_PREFIX}{visit_ref}")
    if current_ttl < 0:
        return False
    r.expire(f"{VISIT_KEY_PREFIX}{visit_ref}", current_ttl + extra_seconds)
    return True
