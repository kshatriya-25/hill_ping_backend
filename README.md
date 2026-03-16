# FastAPI Starter Kit

Production-ready FastAPI backend starter kit with JWT authentication, refresh token rotation, rate limiting, account lockout, and layered security hardening.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.115 |
| Database | PostgreSQL + SQLAlchemy 2.0 |
| Migrations | Alembic |
| Auth | JWT (HS256) via python-jose |
| Password hashing | Argon2 via passlib |
| Rate limiting | slowapi |
| Validation | Pydantic v2 |
| Server | Uvicorn |

---

## Project Structure

```
backend/
├── alembic/                    # Database migrations
│   └── versions/
├── app/
│   ├── api/
│   │   ├── auth/               # Login, refresh, logout endpoints
│   │   ├── healthcheck/        # Health probe
│   │   └── users/              # User CRUD + password change
│   ├── core/
│   │   └── config.py           # Settings loaded from .env
│   ├── database/
│   │   ├── base_class.py       # Declarative base
│   │   └── session.py          # SQLAlchemy engine + session factory
│   ├── middleware/
│   │   ├── logging_middleware.py   # Structured access logging
│   │   └── security_headers.py    # Security response headers
│   ├── modals/
│   │   └── masters.py          # User + RefreshToken ORM models
│   ├── schemas/
│   │   └── masterSchema.py     # Pydantic schemas with validators
│   └── utils/
│       └── utils.py            # JWT helpers, lockout, password utils
├── test/
├── main.py                     # Application entry point
├── requirements.txt
├── alembic.ini
└── .env.example
```

---

## Quick Start

### 1. Clone and install dependencies

```bash
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` — at minimum set:

```env
DB_HOST=localhost
DB_NAME=your_db_name
DB_USER=postgres
DB_PASSWORD=your_db_password

# Generate strong secrets:
# python -c "import secrets; print(secrets.token_hex(64))"
JWT_SECRET_KEY=<64-char hex string>
JWT_REFRESH_SECRET_KEY=<different 64-char hex string>

ALLOWED_ORIGINS=http://localhost:3000
```

### 3. Run database migrations

```bash
alembic upgrade head
```

### 4. Start the server

```bash
uvicorn main:app --reload
```

API docs available at **http://localhost:8000/api/docs** (disabled in production).

---

## API Reference

### Auth — `/api/auth`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/login` | No | Authenticate; returns access + refresh tokens |
| POST | `/refresh` | No | Rotate refresh token; returns new token pair |
| POST | `/logout` | Yes | Revoke a single refresh token |
| POST | `/logout-all` | Yes | Revoke all sessions for the current user |
| GET | `/me` | Yes | Return the authenticated user's profile |

**Login request** (form-encoded):
```
username=alice&password=Secret123!
```

**Login / Refresh response:**
```json
{
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "token_type": "bearer"
}
```

**Using tokens:** send the access token as `Authorization: Bearer <token>`.

---

### Users — `/api/users`

| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/create-superuser` | Public (one-time) | Bootstrap the first admin account |
| POST | `/users/` | Admin | Create a new user |
| GET | `/users/` | Admin | List all users |
| GET | `/users/me` | Any | Own profile |
| GET | `/users/{id}` | Admin or self | Get user by ID |
| PATCH | `/users/{id}` | Admin or self | Partial update (name / email / phone) |
| POST | `/users/{id}/change-password` | Admin or self | Change password; revokes all sessions |
| PATCH | `/users/{id}/activate` | Admin | Activate / deactivate account |
| DELETE | `/users/{id}` | Admin | Delete user |

---

### Health — `/health`

```json
{
  "server_status": "healthy",
  "database_status": "connected"
}
```

---

## Security Features

### Refresh Token Rotation
Every call to `/refresh` revokes the old token and issues a new one. Tokens are stored as SHA-256 hashes in `refresh_tokens` table — the raw value never touches the DB.

**Reuse detection:** replaying a previously revoked refresh token immediately revokes **all** sessions for that user as a compromise response.

### Account Lockout
After `MAX_LOGIN_ATTEMPTS` (default 5) consecutive failures, the account is locked for `LOCKOUT_MINUTES` (default 15). Counters reset on successful login.

### Per-IP Rate Limiting

| Endpoint | Default limit |
|---|---|
| `/api/auth/login` | 10 requests/minute |
| `/api/auth/refresh` | 20 requests/minute |
| Everything else | 60 requests/minute |

All limits are configurable via `.env`.

### Password Policy
Passwords must be at least 8 characters and contain:
- an uppercase letter
- a lowercase letter
- a digit
- a special character (`!@#$%^&*` etc.)

Enforced at the Pydantic schema layer before the handler runs.

### Security Response Headers
Every response includes:

| Header | Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Cache-Control` | `no-store` |

### CORS
`allow_origins=["*"]` is replaced by an explicit whitelist driven by the `ALLOWED_ORIGINS` environment variable. Docs endpoints are hidden in production (`APP_ENV=production`).

### Error Safety
- Unhandled exceptions return a generic 500 — stack traces are logged internally, never sent to the client.
- Login returns the same `401 Invalid credentials` for an unknown username and a wrong password, preventing username enumeration.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `development` / `staging` / `production` |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | — | Database name |
| `DB_USER` | — | Database user |
| `DB_PASSWORD` | — | Database password |
| `JWT_SECRET_KEY` | — | Secret for access tokens (min 32 chars) |
| `JWT_REFRESH_SECRET_KEY` | — | Secret for refresh tokens (different from above) |
| `ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | `10080` | Refresh token lifetime (7 days) |
| `MAX_LOGIN_ATTEMPTS` | `5` | Failed attempts before lockout |
| `LOCKOUT_MINUTES` | `15` | Lockout duration |
| `RATE_LIMIT_LOGIN` | `10/minute` | Login rate limit |
| `RATE_LIMIT_REFRESH` | `20/minute` | Refresh rate limit |
| `RATE_LIMIT_DEFAULT` | `60/minute` | Default rate limit |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated CORS origins |

---

## Running Tests

```bash
pytest
```

---

## Database Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Roll back one step
alembic downgrade -1

# Auto-generate a new migration after model changes
alembic revision --autogenerate -m "describe your change"
```

---

## Production Checklist

- [ ] Set `APP_ENV=production` (disables `/api/docs`, `/api/redoc`)
- [ ] Use secrets manager or CI secrets for `JWT_SECRET_KEY` / `JWT_REFRESH_SECRET_KEY`
- [ ] Run behind HTTPS — HSTS header requires TLS to be meaningful
- [ ] Set `ALLOWED_ORIGINS` to your actual frontend domain(s)
- [ ] Delete or protect `/api/users/create-superuser` after first use
- [ ] Set a strong, unique `DB_PASSWORD`
- [ ] Add a periodic job to purge expired rows from `refresh_tokens`
