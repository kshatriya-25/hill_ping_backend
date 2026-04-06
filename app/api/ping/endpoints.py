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
    Sends property, mediator, guest details (including phone numbers) via WebSocket + FCM.
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

        for admin in admins:
            send_push_to_user(
                user_id=admin.id,
                title="Mediator Booking Match!",
                body=(
                    f"{mediator_name} matched {guest_label}{guest_phone_bit} "
                    f"with {prop_name}. Check-in: {ping.check_in}"
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

    return ping


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
    skip: int = 0,
    limit: int = 30,
    db: Session = Depends(getdb),
    current_user: User = Depends(require_role("owner", "mediator")),
):
    """Owner or mediator views their ping history with optional status filter."""
    q = db.query(PingSessionModel)

    if current_user.role == "owner":
        q = q.filter(PingSessionModel.owner_id == current_user.id)
    else:
        q = q.filter(PingSessionModel.mediator_id == current_user.id)

    if status:
        q = q.filter(PingSessionModel.status == status)

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
