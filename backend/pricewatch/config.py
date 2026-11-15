"""Runtime configuration from environment variables (see .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PRICEWATCH_", env_file=None, extra="ignore")

    data_dir: Path = Path("/data")
    database_url: str | None = None
    port: int = 8086
    log_level: str = "INFO"
    timezone: str = Field(default="America/Toronto", validation_alias="TZ")

    # auth: "password" (built-in login) or "none" (reverse proxy handles it)
    auth_mode: str = "password"
    admin_password: str | None = None
    secret_key: str | None = None
    cookie_secure: bool = False

    # fetching
    user_agent: str | None = None
    contact: str = "self-hosted"
    min_domain_interval: float = 5.0
    domain_jitter: float = 3.0
    request_timeout: float = 20.0
    max_concurrency: int = 4
    default_interval_minutes: int = 360
    hot_interval_minutes: int = 60
    scheduler_enabled: bool = True

    # browser sidecar
    browser_enabled: bool = False
    browser_ws: str = "ws://browser:3000/"
    browser_timeout: float = 30.0

    # notifications (comma separated Apprise URLs); can also be set in the UI
    notify_urls: str = ""

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'pricewatch.db'}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
