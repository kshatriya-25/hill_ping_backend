# HillPing — Ping (availability check) endpoints

import asyncio
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from ...database.session import getdb
from ...database.redis import get_ping_ttl
from ...modals.masters import User
from ...modals.property import Property
from ...schemas.pingSchema import PingRequest, PingResponse, PingSessionResponse, PingStatusResponse
from ...services.ping import (
    create_ping_session,
    handle_ping_response,
    check_and_expire_pending,
    get_pending_pings_for_owner,
    check_instant_confirm,
    PingError,
)
from ...utils.utils import get_current_user, require_guest, require_owner
from ..ws.connection_manager import ws_manager

router = APIRouter(tags=["ping"])


def _notify_owner_bg(owner_id: int, ping_data: dict):
    """Background task: send WebSocket notification to owner."""
    loop = asyncio.new_event_loop()
    try:
        sent = loop.run_until_complete(ws_manager.send_to_user(owner_id, ping_data))
        if not sent:
            # TODO: Phase 9 — FCM push notification fallback
            pass
    finally:
        loop.close()


def _notify_guest_bg(guest_id: int, event_data: dict):
    """Background task: send WebSocket notification to guest."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(ws_manager.send_to_user(guest_id, event_data))
    finally:
        loop.close()


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
        "ttl_seconds": 30,
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
