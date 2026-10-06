from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    app_env: str = "development"
    app_name: str = "BN Bot"
    app_secret_key: str
    discord_token: str
    discord_client_id: str
    discord_client_secret: str
    discord_redirect_uri: str = "http://localhost:8000/auth/callback"
    discord_guild_id: int | None = None
    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    dashboard_url: str = "http://localhost:8000"
    log_level: str = "INFO"

@lru_cache
def get_settings() -> Settings:
    return Settings()
