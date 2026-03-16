# HillPing — WebSocket Connection Manager

import json
import logging
from typing import Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages active WebSocket connections keyed by user_id.
    Used for real-time ping notifications between guests and owners.
    """

    def __init__(self):
        self.active_connections: dict[int, WebSocket] = {}

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        """Accept and register a WebSocket connection."""
        await websocket.accept()
        # Disconnect existing connection for this user if any
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].close()
            except Exception:
                pass
        self.active_connections[user_id] = websocket
        logger.info("WebSocket connected: user_id=%d (total: %d)", user_id, len(self.active_connections))

    def disconnect(self, user_id: int) -> None:
        """Remove a WebSocket connection."""
        self.active_connections.pop(user_id, None)
        logger.info("WebSocket disconnected: user_id=%d (total: %d)", user_id, len(self.active_connections))

    def is_connected(self, user_id: int) -> bool:
        """Check if a user has an active WebSocket connection."""
        return user_id in self.active_connections

    async def send_to_user(self, user_id: int, message: dict) -> bool:
        """
        Send a JSON message to a specific user.
        Returns True if sent successfully, False if user not connected.
        """
        websocket = self.active_connections.get(user_id)
        if websocket is None:
            return False
        try:
            await websocket.send_json(message)
            logger.debug("WebSocket sent to user %d: type=%s", user_id, message.get("type"))
            return True
        except Exception as e:
            logger.warning("WebSocket send failed for user %d: %s", user_id, e)
            self.disconnect(user_id)
            return False

    async def broadcast(self, message: dict, user_ids: list[int] | None = None) -> int:
        """
        Broadcast a message to multiple users (or all connected users).
        Returns count of successful sends.
        """
        targets = user_ids or list(self.active_connections.keys())
        sent = 0
        for uid in targets:
            if await self.send_to_user(uid, message):
                sent += 1
        return sent


# Singleton instance shared across the application
ws_manager = ConnectionManager()
