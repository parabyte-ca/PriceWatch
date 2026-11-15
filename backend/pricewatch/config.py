"""Runtime configuration from environment variables (see .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
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
    admin_username: str = "admin"
    admin_password: str | None = None
    secret_key: str | None = None
    cookie_secure: bool = False

    # fetching
    user_agent: str | None = None
    contact: str = "self-hosted"
    min_domain_interval: float = 20.0
    # extra random spacing as a fraction of the interval (0.3 = up to 30% longer)
    domain_jitter: float = 0.3
    request_timeout: float = 20.0
    max_concurrency: int = 4
    default_interval_minutes: int = 360
    hot_interval_minutes: int = 120
    blackfriday_interval_minutes: int = 30
    blackfriday_max_items: int = 25
    # schedule jitter as a fraction of the interval (0.3 = plus or minus 30%)
    schedule_jitter: float = 0.3
    breaker_blocks: int = 3
    breaker_hours: int = 6
    public_url: str = ""
    scheduler_enabled: bool = True

    # browser sidecar
    browser_enabled: bool = False
    browser_ws: str = "ws://browser:3000/"
    browser_timeout: float = 30.0

    # notifications (comma separated Apprise URLs); can also be set in the UI
    notify_urls: str = ""

    # search (SERP) providers for discovery; each is off without its key
    serpapi_key: str | None = Field(default=None, validation_alias=AliasChoices("SERPAPI_KEY", "PRICEWATCH_SERPAPI_KEY"))
    brightdata_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("BRIGHTDATA_API_KEY", "PRICEWATCH_BRIGHTDATA_API_KEY"))
    brightdata_zone: str = Field(
        default="serp_api1", validation_alias=AliasChoices("BRIGHTDATA_ZONE", "PRICEWATCH_BRIGHTDATA_ZONE"))

    keepa_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("KEEPA_API_KEY", "PRICEWATCH_KEEPA_API_KEY"))
    changedetection_url: str | None = Field(
        default=None, validation_alias=AliasChoices("CHANGEDETECTION_URL", "PRICEWATCH_CHANGEDETECTION_URL"))
    changedetection_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("CHANGEDETECTION_API_KEY", "PRICEWATCH_CHANGEDETECTION_API_KEY"))

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'pricewatch.db'}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
