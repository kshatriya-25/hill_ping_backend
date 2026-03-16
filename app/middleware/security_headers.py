# backend/app/middleware/security_headers.py

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds standard security response headers to every response.

    Headers applied:
    - X-Content-Type-Options      – prevents MIME-type sniffing
    - X-Frame-Options             – clickjacking protection
    - X-XSS-Protection            – legacy XSS filter (belt-and-braces)
    - Strict-Transport-Security   – HSTS (only meaningful over HTTPS)
    - Referrer-Policy             – limits referrer leakage
    - Permissions-Policy          – disables unused browser features
    - Content-Security-Policy     – strict CSP for API-only responses
    - Cache-Control               – prevents caching of API responses
    """

    _DOC_PATHS = {"/docs", "/redoc", "/openapi.json", "/api/docs", "/api/redoc", "/api/openapi.json"}

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=(), usb=()"
        )

        if request.url.path in self._DOC_PATHS:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net unpkg.com; "
                "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net fonts.googleapis.com; "
                "style-src-elem 'self' 'unsafe-inline' cdn.jsdelivr.net fonts.googleapis.com; "
                "font-src 'self' fonts.gstatic.com; "
                "img-src 'self' data: fastapi.tiangolo.com; "
                "connect-src 'self' cdn.jsdelivr.net"
            )
        else:
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"

        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"

        # Remove headers that leak server info
        if "Server" in response.headers:
            del response.headers["Server"]
        if "X-Powered-By" in response.headers:
            del response.headers["X-Powered-By"]

        return response
