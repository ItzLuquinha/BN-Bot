from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    app_env: str = "development"
    app_name: str = "BN Bot"
    app_secret_key: str = Field(min_length=32)
    discord_token: str
    discord_client_id: str
    discord_client_secret: str
    discord_redirect_uri: str = "http://localhost:8000/auth/callback"
    legacy_discord_redirect_uri: str = "http://localhost:8000/auth/callback"
    discord_guild_id: int | None = None
    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    dashboard_url: str = "http://localhost:8000"
    log_level: str = "INFO"

    @field_validator("app_env", mode="before")
    @classmethod
    def normalize_app_env(cls, value: object) -> str:
        return str(value).strip().lower()

    @field_validator("app_secret_key")
    @classmethod
    def validate_app_secret_key(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 32 or len(set(value)) < 8:
            raise ValueError("APP_SECRET_KEY must contain at least 32 characters with sufficient variety")
        if value.casefold() in {"change-me", "changeme", "your-secret-here", "secret-key", "password"}:
            raise ValueError("APP_SECRET_KEY must be a randomly generated secret")
        return value

    @model_validator(mode="after")
    def validate_production_urls(self) -> "Settings":
        if self.app_env == "production":
            if urlparse(self.discord_redirect_uri).scheme != "https":
                raise ValueError("DISCORD_REDIRECT_URI must use HTTPS in production")
            if urlparse(self.dashboard_url).scheme != "https":
                raise ValueError("DASHBOARD_URL must use HTTPS in production")
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings()
