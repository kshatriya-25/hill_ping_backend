# HillPing — WebSocket Connection Manager

import json
import logging
from typing import Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages active WebSocket connections keyed by user_id.
    Supports multiple connections per user (e.g. web + Android simultaneously).
    Used for real-time ping notifications between guests and owners.
    """

    def __init__(self):
        self.active_connections: dict[int, list[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        """Accept and register a WebSocket connection."""
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        total = sum(len(v) for v in self.active_connections.values())
        logger.info(
            "WebSocket connected: user_id=%d (devices: %d, total connections: %d)",
            user_id, len(self.active_connections[user_id]), total,
        )

    def disconnect(self, user_id: int, websocket: WebSocket | None = None) -> None:
        """Remove a WebSocket connection. If websocket is given, remove only that one."""
        if user_id not in self.active_connections:
            return
        if websocket is not None:
            self.active_connections[user_id] = [
                ws for ws in self.active_connections[user_id] if ws is not websocket
            ]
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        else:
            del self.active_connections[user_id]
        total = sum(len(v) for v in self.active_connections.values())
        logger.info("WebSocket disconnected: user_id=%d (total connections: %d)", user_id, total)

    def is_connected(self, user_id: int) -> bool:
        """Check if a user has an active WebSocket connection."""
        return bool(self.active_connections.get(user_id))

    async def send_to_user(self, user_id: int, message: dict) -> bool:
        """
        Send a JSON message to ALL connections for a specific user.
        Returns True if sent to at least one connection successfully.
        """
        connections = self.active_connections.get(user_id)
        if not connections:
            return False
        sent = False
        stale: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_json(message)
                logger.debug("WebSocket sent to user %d: type=%s", user_id, message.get("type"))
                sent = True
            except Exception as e:
                logger.warning("WebSocket send failed for user %d: %s", user_id, e)
                stale.append(ws)
        # Clean up broken connections
        for ws in stale:
            self.disconnect(user_id, ws)
        return sent

    async def broadcast(self, message: dict, user_ids: list[int] | None = None) -> int:
        """
        Broadcast a message to multiple users (or all connected users).
        Returns count of users successfully notified.
        """
        targets = user_ids or list(self.active_connections.keys())
        sent = 0
        for uid in targets:
            if await self.send_to_user(uid, message):
                sent += 1
        return sent


# Singleton instance shared across the application
ws_manager = ConnectionManager()
