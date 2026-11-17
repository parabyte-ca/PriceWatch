"""API schemas. Money is in integer cents; datetimes are serialised as UTC ISO 8601."""

from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, PlainSerializer


def _utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


UTCDateTime = Annotated[datetime, PlainSerializer(_utc, return_type=str | None)]


class ItemBase(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    brand: str | None = None
    model: str | None = None
    gtin: str | None = Field(default=None, pattern=r"^\d{8,14}$")
    category: str | None = None
    image_url: str | None = None
    target_price_cents: int | None = Field(default=None, ge=0)
    max_price_cents: int | None = Field(default=None, ge=0)
    condition: Literal["new", "any"] = "new"
    notes: str | None = None
    priority: int = Field(default=3, ge=1, le=5)
    deadline: date | None = None
    hot: bool = False
    active: bool = True
    exclude_refurbished: bool = True
    exclude_open_box: bool = True
    exclude_used: bool = True
    exclude_marketplace: bool = True
    exclude_bundles: bool = True
    exclude_variants: bool = True
    amazon_history_note: str | None = None
    search_query: str | None = Field(default=None, max_length=300)
    list_id: int | None = None


class ItemCreate(ItemBase):
    pass


class ItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=300)
    brand: str | None = None
    model: str | None = None
    gtin: str | None = Field(default=None, pattern=r"^\d{8,14}$")
    category: str | None = None
    image_url: str | None = None
    target_price_cents: int | None = Field(default=None, ge=0)
    max_price_cents: int | None = Field(default=None, ge=0)
    condition: Literal["new", "any"] | None = None
    notes: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    deadline: date | None = None
    hot: bool | None = None
    active: bool | None = None
    exclude_refurbished: bool | None = None
    exclude_open_box: bool | None = None
    exclude_used: bool | None = None
    exclude_marketplace: bool | None = None
    exclude_bundles: bool | None = None
    exclude_variants: bool | None = None
    amazon_history_note: str | None = None
    search_query: str | None = Field(default=None, max_length=300)
    list_id: int | None = None


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    item_id: int
    url: str
    title: str | None
    status: str
    match_confidence: float | None
    match_method: str | None
    match_reasons: dict | None = None
    discovered_via: str | None = None
    fetch_mode: str | None
    channel: str = "online"
    external_id: str | None = None
    last_condition: str | None = None
    last_seller_type: str | None = None
    retailer_id: int | None
    retailer_name: str | None = None
    price_match: bool = False
    last_price_cents: int | None
    last_was_price_cents: int | None
    last_shipping_cents: int | None
    last_in_stock: bool | None
    last_seller: str | None
    last_checked_at: UTCDateTime | None
    last_success_at: UTCDateTime | None
    last_error: str | None
    consecutive_failures: int
    next_check_at: UTCDateTime | None
    landed: dict | None = None
    last_method: str | None = None


class ItemOut(ItemBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    added_by: int | None = None
    search_terms: str | None = None  # what the price search actually looks for (your query, else a tidy name)
    created_at: UTCDateTime
    updated_at: UTCDateTime
    summary: dict = {}
    sources: list[SourceOut] | None = None
    claimed_by: str | None = None  # gift claim, hidden from the list's owner (the person the list is for)
    claimed_by_me: bool = False
    can_claim: bool = False


class UrlIn(BaseModel):
    url: HttpUrl


class FromUrlIn(BaseModel):
    url: HttpUrl
    list_id: int | None = None
    name: str | None = None
    target_price_cents: int | None = Field(default=None, ge=0)
    hot: bool = False
    priority: int = Field(default=3, ge=1, le=5)


class SourceCreate(BaseModel):
    url: HttpUrl
    fetch_mode: Literal["auto", "search"] | None = None


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["suggested", "confirmed", "rejected"] | None = None
    fetch_mode: Literal["auto", "search", "manual"] | None = None
    channel: str | None = Field(default=None, pattern=r"^(online|warehouse|store:[\w-]{1,30}|province:[A-Z]{2})$")


class DiscoverIn(BaseModel):
    provider: Literal["serpapi", "brightdata"] | None = None
    force: bool = False


class ManualPriceIn(BaseModel):
    store: str = Field(min_length=1, max_length=120)
    channel: str = Field(default="online", pattern=r"^(online|warehouse|store:[\w-]{1,30}|province:[A-Z]{2})$")
    condition: Literal["new", "open_box", "refurbished", "used"] = "new"
    proof: str | None = Field(default=None, max_length=2000)
    price_cents: int = Field(ge=0)
    shipping_cents: int | None = Field(default=None, ge=0)
    was_price_cents: int | None = Field(default=None, ge=0)
    in_stock: bool | None = True
    url: str | None = None


class RetailerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    domain: str
    name: str
    adapter: str
    fetch_mode: str
    min_interval_seconds: float | None
    selectors: dict | None
    respect_robots: bool
    free_shipping_threshold_cents: int | None
    default_shipping_cents: int | None
    price_match: bool
    price_match_notes: str | None
    tax_notes: str | None
    backoff_until: UTCDateTime | None


class RetailerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    fetch_mode: Literal["auto", "search", "manual"] | None = None
    min_interval_seconds: float | None = Field(default=None, ge=20)
    selectors: dict[str, str] | None = None
    respect_robots: bool | None = None
    free_shipping_threshold_cents: int | None = Field(default=None, ge=0)
    default_shipping_cents: int | None = Field(default=None, ge=0)
    price_match: bool | None = None
    price_match_notes: str | None = None
    tax_notes: str | None = None
    clear_backoff: bool | None = None


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    item_id: int | None
    rule_type: str
    title: str
    body: str
    url: str | None
    status: str
    error: str | None
    created_at: UTCDateTime
    sent_at: UTCDateTime | None


class LoginIn(BaseModel):
    password: str
