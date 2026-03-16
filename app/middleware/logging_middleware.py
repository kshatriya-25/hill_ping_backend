# backend/app/middleware/logging_middleware.py

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("api.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs every request with:
    - A unique request-ID (echoed in the response header for traceability)
    - HTTP method, path, query string
    - Client IP (respects X-Forwarded-For when behind a proxy)
    - Response status code
    - Wall-clock duration in milliseconds
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())
        start = time.perf_counter()

        client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")

        logger.info(
            "→ %s %s%s [%s] request_id=%s",
            request.method,
            request.url.path,
            f"?{request.url.query}" if request.url.query else "",
            client_ip,
            request_id,
        )

        response: Response = await call_next(request)

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "← %s %s %d %.1fms request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )

        response.headers["X-Request-ID"] = request_id
        return response
