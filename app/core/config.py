# OM VIGHNHARTAYE NAMO NAMAH :

import os
from urllib.parse import quote_plus
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).resolve().parent.parent.parent / '.env'

if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    print("Warning: .env file not found. Environment variables may not be loaded.")


class Settings:

    PROJECT_NAME: str = "HillPing"
    PROJECT_VERSION: str = "1.0.0"

    APP_ENV: str = os.getenv("APP_ENV", "development")

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins, e.g. "http://localhost:3000,https://app.example.com"
    ALLOWED_ORIGINS: list[str] = [
        o.strip()
        for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
        if o.strip()
    ]

    # ── Upload directories ─────────────────────────────────────────────────────
    UPLOAD_BASE_DIR = "uploads"
    LOGO_DIR = os.path.join(UPLOAD_BASE_DIR, "logos")
    DOCUMENT_DIR = os.path.join(UPLOAD_BASE_DIR, "documents")
    THUMBNAIL_DIR = "uploads/logo_imgs"
    SITE_DOCUMENT_DIR = "uploads/site_documents"

    # ── Database ───────────────────────────────────────────────────────────────
    DB_USER: str = os.getenv("DB_USER", "")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "5432")
    DB_NAME: str = os.getenv("DB_NAME", "")
    DATABASE_URL: str = f"postgresql://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    # ── JWT ────────────────────────────────────────────────────────────────────
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
    JWT_REFRESH_SECRET_KEY: str = os.getenv("JWT_REFRESH_SECRET_KEY", "")

    # Default ~6 months; override with ACCESS_TOKEN_EXPIRE_MINUTES in .env
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 183)))
    # Default 365 days — long-lived sessions; override via REFRESH_TOKEN_EXPIRE_MINUTES in .env
    REFRESH_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 365)))

    # ── Account lockout ────────────────────────────────────────────────────────
    MAX_LOGIN_ATTEMPTS: int = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
    LOCKOUT_MINUTES: int = int(os.getenv("LOCKOUT_MINUTES", "15"))

    # ── Rate limiting (slowapi) ────────────────────────────────────────────────
    # Auth endpoints: stricter
    RATE_LIMIT_LOGIN: str = os.getenv("RATE_LIMIT_LOGIN", "10/minute")
    RATE_LIMIT_REFRESH: str = os.getenv("RATE_LIMIT_REFRESH", "20/minute")
    # General API endpoints
    RATE_LIMIT_DEFAULT: str = os.getenv("RATE_LIMIT_DEFAULT", "60/minute")
    # Ping endpoint: max 3 pings per property per guest per hour
    RATE_LIMIT_PING: str = os.getenv("RATE_LIMIT_PING", "3/minute")

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    REDIS_URL: str = os.getenv("REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")

    # ── Razorpay ──────────────────────────────────────────────────────────────
    RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "")

    # ── FCM (Firebase Cloud Messaging) ────────────────────────────────────────
    FCM_CREDENTIALS_PATH: str = os.getenv("FCM_CREDENTIALS_PATH", "")

    # ── HillPing platform settings ────────────────────────────────────────────
    PING_TTL_SECONDS: int = int(os.getenv("PING_TTL_SECONDS", "30"))
    COMMISSION_PERCENTAGE: float = float(os.getenv("COMMISSION_PERCENTAGE", "10"))
    INSTANT_CONFIRM_THRESHOLD: float = float(os.getenv("INSTANT_CONFIRM_THRESHOLD", "95"))

    # ── V2: Mediator platform settings ─────────────────────────────────────────
    VISIT_HOLD_TTL_SECONDS: int = int(os.getenv("VISIT_HOLD_TTL_SECONDS", "2700"))  # 45 minutes
    MAX_BULK_PING: int = int(os.getenv("MAX_BULK_PING", "3"))
    MAX_TOUR_STOPS: int = int(os.getenv("MAX_TOUR_STOPS", "3"))
    GUEST_ACCESS_CODE_VALIDITY_HOURS: int = int(os.getenv("GUEST_ACCESS_CODE_VALIDITY_HOURS", "24"))
    RESIDUAL_COMMISSION_MONTHS: int = int(os.getenv("RESIDUAL_COMMISSION_MONTHS", "12"))

    # ── SMS Gateway ─────────────────────────────────────────────────────────────
    SMS_PROVIDER: str = os.getenv("SMS_PROVIDER", "")  # msg91 or twilio
    MSG91_AUTH_KEY: str = os.getenv("MSG91_AUTH_KEY", "")
    MSG91_SENDER_ID: str = os.getenv("MSG91_SENDER_ID", "")
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER: str = os.getenv("TWILIO_FROM_NUMBER", "")

    # ── Mediator match: in-app "Call" hotline (digits; shown in mediator app after owner accepts)
    MEDIATOR_MATCH_HOTLINE: str = os.getenv("MEDIATOR_MATCH_HOTLINE", "6384075907").strip()

    # ── Upload directories (extended) ─────────────────────────────────────────
    PROPERTY_PHOTO_DIR: str = os.path.join(UPLOAD_BASE_DIR, "property_photos")


settings = Settings()
