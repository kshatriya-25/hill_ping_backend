#OM VIGHNHARTAYE NAMO NAMAH :
import logging
import logging.config

import os
from fastapi import FastAPI, Request, status
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.healthcheck.status import router as healthRouter
from app.api.users.endpoints import router as user_Router
from app.api.auth.endpoints import router as auth_Router
from app.api.properties.endpoints import router as properties_Router
from app.api.amenities.endpoints import router as amenities_Router
from app.api.reliability.endpoints import router as reliability_Router
from app.api.ping.endpoints import router as ping_Router
from app.api.ws.endpoints import router as ws_Router
from app.api.bookings.endpoints import router as bookings_Router
from app.api.payouts.endpoints import router as payouts_Router
from app.api.reviews.endpoints import router as reviews_Router
from app.api.coupons.endpoints import router as coupons_Router
from app.api.notifications.endpoints import router as notifications_Router
from app.api.wishlist.endpoints import router as wishlist_Router
from app.api.admin.endpoints import router as admin_Router
from app.core.config import settings
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.logging_middleware import RequestLoggingMiddleware


# ── Logging configuration ──────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Rate limiter (shared instance) ────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT_DEFAULT])


# ── Router registration ────────────────────────────────────────────────────────

def include_routers(app: FastAPI) -> None:
    app.include_router(healthRouter)
    app.include_router(user_Router, prefix="/api/users")
    app.include_router(auth_Router, prefix="/api/auth")
    app.include_router(properties_Router, prefix="/api/properties")
    app.include_router(amenities_Router, prefix="/api/amenities")
    app.include_router(reliability_Router, prefix="/api/reliability")
    app.include_router(ping_Router, prefix="/api/ping")
    app.include_router(ws_Router)
    app.include_router(bookings_Router, prefix="/api/bookings")
    app.include_router(payouts_Router, prefix="/api/payouts")
    app.include_router(reviews_Router, prefix="/api/reviews")
    app.include_router(coupons_Router, prefix="/api/coupons")
    app.include_router(notifications_Router, prefix="/api/notifications")
    app.include_router(wishlist_Router, prefix="/api/wishlist")
    app.include_router(admin_Router, prefix="/api/admin")


# ── Application factory ────────────────────────────────────────────────────────

def start_application() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.PROJECT_VERSION,
        docs_url="/api/docs" if settings.APP_ENV != "production" else None,
        redoc_url="/api/redoc" if settings.APP_ENV != "production" else None,
        openapi_url="/api/openapi.json" if settings.APP_ENV != "production" else None,
    )

    # ── Rate limiter ───────────────────────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # ── Security headers ───────────────────────────────────────────────────────
    app.add_middleware(SecurityHeadersMiddleware)

    # ── Request / access logging ───────────────────────────────────────────────
    app.add_middleware(RequestLoggingMiddleware)

    # ── CORS ───────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    # ── Global exception handlers ──────────────────────────────────────────────

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Return structured 422 responses with clear field-level error messages."""
        errors = [
            {"field": ".".join(str(loc) for loc in e["loc"]), "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "Validation error", "errors": errors},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """Catch-all: log the error internally, never leak stack traces to clients."""
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal server error occurred."},
        )

    # ── Static files (uploaded photos) ──────────────────────────────────────
    os.makedirs(settings.UPLOAD_BASE_DIR, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_BASE_DIR), name="uploads")

    # ── Routers ────────────────────────────────────────────────────────────────
    include_routers(app)

    logger.info("Application '%s' v%s starting [env=%s]", settings.PROJECT_NAME, settings.PROJECT_VERSION, settings.APP_ENV)
    return app


app = start_application()
