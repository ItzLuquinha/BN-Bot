import hashlib
import hmac
import logging
import os
import re
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

from api.core.security import get_secret_key, validate_security_configuration
from api.database import dispose_engine, get_db, validate_database_configuration
from api.routers import auth, guilds


def _allowed_origins() -> list[str]:
    configured = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    environment = os.getenv("APP_ENV", "development").strip().lower()
    if configured:
        origins = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    elif environment == "production":
        dashboard_url = os.getenv("DASHBOARD_URL", "").strip()
        parsed = urlparse(dashboard_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise RuntimeError("Production requires CORS_ALLOWED_ORIGINS or an HTTPS DASHBOARD_URL")
        origins = [f"{parsed.scheme}://{parsed.netloc}"]
    else:
        origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
    if not origins or "*" in origins:
        raise RuntimeError("CORS_ALLOWED_ORIGINS must contain explicit origins and cannot use a wildcard")
    for origin in origins:
        parsed = urlparse(origin)
        try:
            parsed.port
        except ValueError:
            raise RuntimeError("Each CORS origin must have a valid port") from None
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise RuntimeError("Each CORS origin must be an origin without credentials, path, query, or fragment")
        if environment == "production" and parsed.scheme != "https":
            raise RuntimeError("Production CORS origins must use HTTPS")
    return list(dict.fromkeys(origins))


def _validated_origin(url: str, name: str, production: bool) -> str:
    parsed = urlparse(url.strip())
    try:
        parsed.port
    except ValueError:
        raise RuntimeError(f"{name} must contain a valid port") from None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise RuntimeError(f"{name} must be an absolute HTTP(S) URL without credentials")
    if parsed.query or parsed.fragment:
        raise RuntimeError(f"{name} cannot contain a query or fragment")
    if production and parsed.scheme != "https":
        raise RuntimeError(f"{name} must use HTTPS in production")
    return f"{parsed.scheme}://{parsed.netloc}"


def validate_public_urls(origins: list[str]) -> None:
    production = os.getenv("APP_ENV", "development").strip().lower() == "production"
    dashboard_url = os.getenv("DASHBOARD_URL", "http://localhost:5173").strip()
    dashboard_origin = _validated_origin(dashboard_url, "DASHBOARD_URL", production)
    if dashboard_origin not in origins:
        raise RuntimeError("The DASHBOARD_URL origin must be included in CORS_ALLOWED_ORIGINS")
    callback = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8000/api/v1/auth/callback").strip()
    _validated_origin(callback, "DISCORD_REDIRECT_URI", production)


class OAuthQueryRedactionFilter(logging.Filter):
    _secret_query = re.compile(r"([?&](?:code|state|access_token|token)=)[^&\s]+", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(self._redact(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: self._redact(value) for key, value in record.args.items()}
        return True

    @classmethod
    def _redact(cls, value):
        if isinstance(value, str):
            return cls._secret_query.sub(r"\1[redacted]", value)
        return value


logging.getLogger("uvicorn.access").addFilter(OAuthQueryRedactionFilter())
SESSION_SECRET_KEY = hmac.new(get_secret_key().encode("utf-8"), b"bn-bot-api-session-cookie-v1", hashlib.sha256).hexdigest()
CORS_ORIGINS = _allowed_origins()
validate_public_urls(CORS_ORIGINS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_security_configuration()
    validate_database_configuration()
    try:
        yield
    finally:
        await dispose_engine()


app = FastAPI(
    title="Dashboard REST API",
    description="API REST do dashboard React do BN Bot",
    version="1.1.0",
    lifespan=lifespan,
)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY, https_only=os.getenv("APP_ENV", "development").lower() == "production", same_site="lax", session_cookie="bn_api_session", max_age=600)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
    expose_headers=["Retry-After"],
    max_age=600,
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Autenticação"])
app.include_router(auth.router, prefix="/auth", include_in_schema=False)
app.include_router(guilds.router, prefix="/api/v1/guilds", tags=["Servidores e configurações"])


@app.get("/health", tags=["Status"])
async def health():
    return {"status": "online"}


@app.get("/health/db", tags=["Status"])
async def health_db(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT 1"))
    result.scalar_one()
    return {"status": "connected"}
