# HillPing — Ping (availability check) endpoints

import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from ...database.session import getdb, SessionLocal
from ...database.redis import get_ping_ttl
from ...modals.masters import User
from ...modals.property import Property
from ...modals.ping import PingSession as PingSessionModel
from ...schemas.pingSchema import PingRequest, PingResponse, PingSessionResponse, PingStatusResponse
from ...services.ping import (
    create_ping_session,
    handle_ping_response,
    check_and_expire_pending,
    get_pending_pings_for_owner,
    check_instant_confirm,
    PingError,
    effective_guest_name_phone_for_mediator_ping,
    ping_session_to_response_dict,
)
from ...utils.utils import get_current_user, require_guest, require_owner, require_role
from ..ws.connection_manager import ws_manager

router = APIRouter(tags=["ping"])
_logger = logging.getLogger(__name__)


def _notify_owner_bg(owner_id: int, ping_data: dict):
    """Background task: send WebSocket + FCM push notification to owner."""
    # 1. Try WebSocket (real-time, for foreground app)
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(ws_manager.send_to_user(owner_id, ping_data))
    finally:
        loop.close()

    # 2. Always send FCM push (for background/closed app — Android handles dedup)
    _logger.info("FCM: Sending push notification to owner %d", owner_id)
    try:
        from ...services.notifications import send_ping_notification
        db = SessionLocal()
        try:
            result = send_ping_notification(owner_id, ping_data, db)
            _logger.info("FCM: send_ping_notification returned %s", result)
        finally:
            db.close()
    except Exception as e:
        _logger.error("FCM push failed: %s", e, exc_info=True)


def _notify_guest_bg(guest_id: int, event_data: dict):
    """Background task: send WebSocket notification to guest."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(ws_manager.send_to_user(guest_id, event_data))
    finally:
        loop.close()


def _notify_admins_bg(ping_id: int):
    """
    Background task: notify all admin users when a mediator-initiated ping is accepted.
    Sends property, mediator, guest details (including phone numbers) and a price
    breakdown (owner price, mediator commission, platform fee, service fee, total)
    via WebSocket + FCM.
    """
    db = SessionLocal()
    try:
        ping = db.query(PingSessionModel).filter(PingSessionModel.id == ping_id).first()
        if not ping or not ping.mediator_id or ping.status != "accepted":
            return

        # Gather details
        prop = db.query(Property).filter(Property.id == ping.property_id).first()
        guest = db.query(User).filter(User.id == ping.guest_id).first()
        mediator = db.query(User).filter(User.id == ping.mediator_id).first()
        owner = db.query(User).filter(User.id == ping.owner_id).first()

        g_name, g_phone = effective_guest_name_phone_for_mediator_ping(ping, guest)

        # ── Price breakdown ───────────────────────────────────────────────────
        # Recompute from the room locked in by _apply_accepted_ping_pricing so admin
        # sees the exact split: owner rack subtotal + per-night mediator commission +
        # per-night platform fee + service fee (% on owner subtotal).
        from ...modals.property import Room
        from ...services.pricing import calculate_booking_price

        breakdown_summary = {
            "nights": 0,
            "owner_subtotal": 0.0,           # sum(room.price_weekday|weekend) across nights
            "mediator_commission_total": 0.0, # room.mediator_commission * nights
            "platform_fee_total": 0.0,        # room.platform_fee * nights
            "service_fee": 0.0,               # platform commission % on owner_subtotal
            "total_amount": 0.0,              # full guest total = base + service_fee
        }
        room = db.query(Room).filter(Room.id == ping.room_id).first() if ping.room_id else None
        if room and prop:
            try:
                pricing = calculate_booking_price(
                    room,
                    ping.check_in,
                    ping.check_out,
                    commission_override=prop.commission_override,
                    commission_type=getattr(prop, "commission_type", None) or "percentage",
                )
                nights = pricing["nights"]
                # base_amount = owner_subtotal + (mediator_commission + platform_fee) * nights
                # We re-derive the owner subtotal by walking the per-night breakdown.
                owner_subtotal = sum(float(b["owner_price"]) for b in pricing["breakdown"])
                mc_per_night = float(getattr(room, "mediator_commission", 0) or 0)
                pf_per_night = float(getattr(room, "platform_fee", 0) or 0)
                breakdown_summary = {
                    "nights": nights,
                    "owner_subtotal": round(owner_subtotal, 2),
                    "mediator_commission_total": round(mc_per_night * nights, 2),
                    "platform_fee_total": round(pf_per_night * nights, 2),
                    "service_fee": round(float(pricing["service_fee"]), 2),
                    "total_amount": round(float(pricing["total_amount"]), 2),
                }
            except Exception as e:
                _logger.warning("Admin breakdown computation failed for ping %d: %s", ping_id, e)

        admin_msg = {
            "type": "mediator_ping_accepted",
            "session_id": ping.session_id,
            "property_id": ping.property_id,
            "property_name": prop.name if prop else "",
            "property_location": prop.city if prop else "",
            "owner_id": ping.owner_id,
            "owner_name": owner.name if owner else "",
            "owner_phone": owner.phone if owner else "",
            "mediator_id": ping.mediator_id,
            "mediator_name": mediator.name if mediator else "",
            "mediator_phone": mediator.phone if mediator else "",
            "guest_id": ping.guest_id,
            "guest_name": g_name or "",
            "guest_phone": g_phone or "",
            "check_in": str(ping.check_in),
            "check_out": str(ping.check_out),
            "guests_count": ping.guests_count,
            "response_time_seconds": ping.owner_response_time,
            # Price breakdown — added 2026-05; admin clients display these.
            "nights": breakdown_summary["nights"],
            "owner_subtotal": breakdown_summary["owner_subtotal"],
            "mediator_commission_total": breakdown_summary["mediator_commission_total"],
            "platform_fee_total": breakdown_summary["platform_fee_total"],
            "service_fee": breakdown_summary["service_fee"],
            "total_amount": breakdown_summary["total_amount"],
        }

        # Find all admin users
        admins = db.query(User).filter(User.role == "admin", User.is_active == True).all()
        if not admins:
            _logger.debug("No active admins to notify")
            return

        # Send WebSocket to all admins
        loop = asyncio.new_event_loop()
        try:
            for admin in admins:
                loop.run_until_complete(ws_manager.send_to_user(admin.id, admin_msg))
        finally:
            loop.close()

        # Send FCM push to all admins
        from ...services.notifications import send_push_to_user
        guest_label = g_name or "Walk-in guest"
        guest_phone_bit = f" ({g_phone})" if g_phone else ""
        mediator_name = mediator.name if mediator else "Mediator"
        prop_name = prop.name if prop else "a property"

        def _fcm_val(v):
            if v is None:
                return ""
            return str(v)

        fcm_flat = {k: _fcm_val(v) for k, v in admin_msg.items()}

        # One-line price summary for the FCM body — only when we have a real total.
        total = breakdown_summary["total_amount"]
        if total > 0:
            money_line = (
                f" · Total ₹{int(round(total))} "
                f"(Owner ₹{int(round(breakdown_summary['owner_subtotal']))}, "
                f"Mediator ₹{int(round(breakdown_summary['mediator_commission_total']))}, "
                f"Platform ₹{int(round(breakdown_summary['platform_fee_total'] + breakdown_summary['service_fee']))})"
            )
        else:
            money_line = ""

        for admin in admins:
            send_push_to_user(
                user_id=admin.id,
                title="Mediator Booking Match!",
                body=(
                    f"{mediator_name} matched {guest_label}{guest_phone_bit} "
                    f"with {prop_name}. Check-in: {ping.check_in}{money_line}"
                ),
                data=fcm_flat,
                db=db,
            )

        _logger.info(
            "Admin notification sent for mediator ping %s: %d admins notified",
            ping.session_id, len(admins),
        )
    except Exception as e:
        _logger.error("Admin notification failed for ping %d: %s", ping_id, e, exc_info=True)
    finally:
        db.close()


@router.post("/check-availability", response_model=PingSessionResponse)
def check_availability(
    data: PingRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_guest),
):
    """
    Guest initiates an availability check.
    Creates a 30-second ping session and notifies the owner via WebSocket.
    If the property has instant-confirm enabled, the booking is auto-confirmed.
    """
    # Check instant confirm
    if check_instant_confirm(data.property_id, db):
        # TODO: create booking directly (Phase 6 integration)
        pass

    try:
        ping = create_ping_session(
            guest_id=current_user.id,
            property_id=data.property_id,
            room_id=data.room_id,
            check_in=data.check_in,
            check_out=data.check_out,
            guests_count=data.guests_count,
            db=db,
        )
    except PingError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    # Notify owner via WebSocket (FCM fallback if not connected)
    prop = db.query(Property).filter(Property.id == data.property_id).first()
    background_tasks.add_task(_notify_owner_bg, ping.owner_id, {
        "type": "ping_received",
        "session_id": ping.session_id,
        "property_id": ping.property_id,
        "property_name": prop.name if prop else "",
        "check_in": str(data.check_in),
        "check_out": str(data.check_out),
        "guests_count": data.guests_count,
        "ttl_seconds": int((ping.expires_at - ping.created_at).total_seconds()),
        "expires_at": ping.expires_at.isoformat(),
    })

    return ping


@router.post("/{session_id}/respond", response_model=PingSessionResponse)
def respond_to_ping(
    session_id: str,
    data: PingResponse,
    background_tasks: BackgroundTasks,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_owner),
):
    """
    Owner accepts or rejects a ping.
    Must respond within 30 seconds of ping creation.
    """
    try:
        ping = handle_ping_response(
            session_id=session_id,
            owner_id=current_user.id,
            action=data.action,
            db=db,
        )
    except PingError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    # Notify guest via WebSocket
    prop = db.query(Property).filter(Property.id == ping.property_id).first()
    event_data = {
        "type": f"ping_{ping.status}",
        "session_id": session_id,
        "property_id": ping.property_id,
        "property_name": prop.name if prop else "",
    }
    background_tasks.add_task(_notify_guest_bg, ping.guest_id, event_data)

    # V2: Also notify mediator if this was a mediator-initiated ping
    if ping.mediator_id and ping.mediator_id != ping.guest_id:
        background_tasks.add_task(_notify_guest_bg, ping.mediator_id, event_data)

    # Notify admins when a mediator-initiated ping is accepted
    if ping.mediator_id and ping.status == "accepted":
        background_tasks.add_task(_notify_admins_bg, ping.id)

    # TODO: Phase 6 — trigger payment capture on accept, release on reject

    return ping_session_to_response_dict(ping, db)


@router.get("/{session_id}/status", response_model=PingStatusResponse)
def ping_status(
    session_id: str,
    db: Session = Depends(getdb),
    current_user: User = Depends(get_current_user),
):
    """
    Both guest and owner can poll the status of a ping session.
    If the Redis TTL has expired, this automatically marks it as expired.
    """
    status = check_and_expire_pending(session_id, db)

    if status == "not_found":
        raise HTTPException(status_code=404, detail="Ping session not found")

    remaining = max(0, get_ping_ttl(session_id)) if status == "pending" else 0

    # Get property name for display
    from ...modals.ping import PingSession
    ping = db.query(PingSession).filter(PingSession.session_id == session_id).first()
    property_name = None
    if ping:
        prop = db.query(Property).filter(Property.id == ping.property_id).first()
        property_name = prop.name if prop else None

    return PingStatusResponse(
        session_id=session_id,
        status=status,
        remaining_seconds=remaining,
        property_name=property_name,
    )


@router.get("/my-pending", response_model=list[PingSessionResponse])
def my_pending_pings(
    db: Session = Depends(getdb),
    current_user: User = Depends(require_owner),
):
    """Owner views their pending ping requests."""
    pings = get_pending_pings_for_owner(current_user.id, db)

    # Auto-expire any that have timed out
    result = []
    for ping in pings:
        status = check_and_expire_pending(ping.session_id, db)
        if status == "pending":
            db.refresh(ping)
            result.append(ping)

    return result


@router.get("/my-history")
def my_ping_history(
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    skip: int = 0,
    limit: int = 30,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("owner", "mediator")),
):
    """
    Owner or mediator views their ping history.
    Optional filters: status, date_from / date_to (ISO YYYY-MM-DD on created_at).
    """
    import datetime as _dt
    q = db.query(PingSessionModel)

    if current_user.role == "owner":
        q = q.filter(PingSessionModel.owner_id == current_user.id)
    else:
        q = q.filter(PingSessionModel.mediator_id == current_user.id)

    if status:
        q = q.filter(PingSessionModel.status == status)

    if date_from:
        try:
            df = _dt.date.fromisoformat(date_from)
            q = q.filter(PingSessionModel.created_at >= _dt.datetime.combine(df, _dt.time.min))
        except ValueError:
            raise HTTPException(status_code=422, detail="date_from must be YYYY-MM-DD")
    if date_to:
        try:
            dt_end = _dt.date.fromisoformat(date_to)
            # Inclusive: filter < (date_to + 1 day) so the whole day is included.
            q = q.filter(PingSessionModel.created_at < _dt.datetime.combine(dt_end + _dt.timedelta(days=1), _dt.time.min))
        except ValueError:
            raise HTTPException(status_code=422, detail="date_to must be YYYY-MM-DD")

    total = q.count()
    pings = q.order_by(PingSessionModel.created_at.desc()).offset(skip).limit(limit).all()

    items = []
    for p in pings:
        # Resolve property name
        prop = db.query(Property).filter(Property.id == p.property_id).first()
        # Resolve guest/mediator names
        guest = db.query(User).filter(User.id == p.guest_id).first() if p.guest_id else None
        mediator = db.query(User).filter(User.id == p.mediator_id).first() if p.mediator_id else None

        items.append({
            "id": p.id,
            "session_id": p.session_id,
            "property_id": p.property_id,
            "property_name": prop.name if prop else None,
            "guest_id": p.guest_id,
            "guest_name": guest.name if guest else None,
            "guest_phone": guest.phone if guest else None,
            "mediator_id": p.mediator_id,
            "mediator_name": mediator.name if mediator else None,
            "check_in": str(p.check_in),
            "check_out": str(p.check_out),
            "guests_count": p.guests_count,
            "status": p.status,
            "response_time_seconds": p.owner_response_time,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "responded_at": p.responded_at.isoformat() if p.responded_at else None,
        })

    return {
        "total": total,
        "pings": items,
        "has_more": (skip + limit) < total,
    }
