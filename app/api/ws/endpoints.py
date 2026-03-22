# HillPing — WebSocket endpoints

import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import jwt, JWTError

from ...core.config import settings
from ...database.session import SessionLocal
from ...modals.masters import User
from .connection_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    """
    WebSocket connection for real-time events.
    Authentication via JWT access token passed as a path parameter.

    Events sent to owner:
      - ping_received: new availability check from a guest
      - ping_expired: a pending ping timed out

    Events sent to guest:
      - ping_accepted: owner accepted the availability check
      - ping_rejected: owner rejected the availability check
      - ping_expired: owner did not respond in time
      - booking_confirmed: booking is confirmed and payment captured
    """
    # ── Authenticate via JWT ──────────────────────────────────────────────
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    if payload.get("type") != "access":
        await websocket.close(code=4001, reason="Invalid token type")
        return

    user_id = payload.get("user_id")
    if user_id is None:
        await websocket.close(code=4001, reason="Invalid token payload")
        return

    # Verify user exists and is active
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            await websocket.close(code=4003, reason="User not found or deactivated")
            return
        user_role = user.role
    finally:
        db.close()

    # ── Connect ───────────────────────────────────────────────────────────
    await ws_manager.connect(user_id, websocket)

    try:
        while True:
            # Keep connection alive, handle incoming messages
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "heartbeat":
                await websocket.send_json({"type": "heartbeat_ack"})

            # Owner can respond to pings via WebSocket too
            elif msg_type == "ping_response" and user_role == "owner":
                session_id = data.get("session_id")
                action = data.get("action")  # "accept" or "reject"
                if session_id and action in ("accept", "reject"):
                    await _handle_ws_ping_response(user_id, session_id, action, websocket)

    except WebSocketDisconnect:
        ws_manager.disconnect(user_id, websocket)
    except Exception as e:
        logger.exception("WebSocket error for user %d: %s", user_id, e)
        ws_manager.disconnect(user_id, websocket)


async def _handle_ws_ping_response(owner_id: int, session_id: str, action: str, websocket: WebSocket):
    """Handle a ping response received via WebSocket."""
    from ...services.ping import handle_ping_response, PingError

    db = SessionLocal()
    try:
        ping = handle_ping_response(session_id, owner_id, action, db)

        # Notify the guest
        from ...modals.property import Property
        prop = db.query(Property).filter(Property.id == ping.property_id).first()
        guest_msg = {
            "type": f"ping_{ping.status}",
            "session_id": session_id,
            "property_id": ping.property_id,
            "property_name": prop.name if prop else "",
        }
        await ws_manager.send_to_user(ping.guest_id, guest_msg)

        # V2: Also notify mediator if this was a mediator-initiated ping
        if ping.mediator_id and ping.mediator_id != ping.guest_id:
            await ws_manager.send_to_user(ping.mediator_id, guest_msg)

        # Notify admins when a mediator-initiated ping is accepted
        if ping.mediator_id and ping.status == "accepted":
            from ..ping.endpoints import _notify_admins_bg
            import asyncio
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, _notify_admins_bg, ping.id)

        # Confirm to owner
        await websocket.send_json({
            "type": "ping_response_ack",
            "session_id": session_id,
            "status": ping.status,
        })

    except PingError as e:
        await websocket.send_json({
            "type": "error",
            "detail": e.detail,
        })
    finally:
        db.close()
