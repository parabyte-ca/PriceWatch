"""ORM models. Money is stored in integer cents (CAD); timestamps are naive UTC."""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .timeutil import utcnow


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    brand: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120))
    gtin: Mapped[str | None] = mapped_column(String(20), index=True)
    category: Mapped[str | None] = mapped_column(String(120))
    image_url: Mapped[str | None] = mapped_column(String(1000))
    target_price_cents: Mapped[int | None] = mapped_column(Integer)
    max_price_cents: Mapped[int | None] = mapped_column(Integer)
    condition: Mapped[str] = mapped_column(String(20), default="new")
    notes: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    deadline: Mapped[date | None] = mapped_column(Date)
    hot: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # exclusion toggles (True = exclude)
    exclude_refurbished: Mapped[bool] = mapped_column(Boolean, default=True)
    exclude_open_box: Mapped[bool] = mapped_column(Boolean, default=True)
    exclude_used: Mapped[bool] = mapped_column(Boolean, default=True)
    exclude_marketplace: Mapped[bool] = mapped_column(Boolean, default=True)
    exclude_bundles: Mapped[bool] = mapped_column(Boolean, default=True)
    exclude_variants: Mapped[bool] = mapped_column(Boolean, default=True)
    amazon_history_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    sources: Mapped[list["SourceLink"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="SourceLink.id"
    )


class Retailer(Base):
    __tablename__ = "retailers"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    adapter: Mapped[str] = mapped_column(String(50), default="generic")
    fetch_mode: Mapped[str] = mapped_column(String(20), default="auto")  # auto | http | browser
    min_interval_seconds: Mapped[float | None] = mapped_column(Float)
    selectors: Mapped[dict | None] = mapped_column(JSON)
    respect_robots: Mapped[bool] = mapped_column(Boolean, default=True)
    free_shipping_threshold_cents: Mapped[int | None] = mapped_column(Integer)
    default_shipping_cents: Mapped[int | None] = mapped_column(Integer)
    price_match: Mapped[bool] = mapped_column(Boolean, default=False)
    price_match_notes: Mapped[str | None] = mapped_column(Text)
    tax_notes: Mapped[str | None] = mapped_column(Text)
    backoff_until: Mapped[datetime | None] = mapped_column(DateTime)
    backoff_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SourceLink(Base):
    __tablename__ = "source_links"
    __table_args__ = (UniqueConstraint("item_id", "url", name="uq_source_item_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    retailer_id: Mapped[int | None] = mapped_column(ForeignKey("retailers.id"))
    url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="confirmed")  # suggested|confirmed|rejected
    match_confidence: Mapped[float | None] = mapped_column(Float)
    match_method: Mapped[str | None] = mapped_column(String(30))
    fetch_mode: Mapped[str | None] = mapped_column(String(20))  # overrides retailer when set
    etag: Mapped[str | None] = mapped_column(String(300))
    last_modified: Mapped[str | None] = mapped_column(String(100))
    last_price_cents: Mapped[int | None] = mapped_column(Integer)
    last_was_price_cents: Mapped[int | None] = mapped_column(Integer)
    last_shipping_cents: Mapped[int | None] = mapped_column(Integer)
    last_in_stock: Mapped[bool | None] = mapped_column(Boolean)
    last_seller: Mapped[str | None] = mapped_column(String(200))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    item: Mapped[Item] = relationship(back_populates="sources")
    retailer: Mapped[Retailer | None] = relationship()


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (Index("ix_obs_item_time", "item_id", "observed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    source_link_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_links.id", ondelete="CASCADE"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    price_cents: Mapped[int | None] = mapped_column(Integer)
    was_price_cents: Mapped[int | None] = mapped_column(Integer)
    shipping_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="CAD")
    in_stock: Mapped[bool | None] = mapped_column(Boolean)
    seller: Mapped[str | None] = mapped_column(String(200))
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(20), default="http")  # http|browser|manual|not_modified


class FetchRun(Base):
    __tablename__ = "fetch_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_link_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_links.id", ondelete="SET NULL"), index=True
    )
    domain: Mapped[str] = mapped_column(String(200), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))  # ok|not_modified|no_price|http_error|blocked|robots|error
    http_status: Mapped[int | None] = mapped_column(Integer)
    method: Mapped[str | None] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    rule_type: Mapped[str] = mapped_column(String(30))  # target|drop_pct|all_time_low|back_in_stock|source_failing
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    threshold: Mapped[float | None] = mapped_column(Float)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    rule_type: Mapped[str] = mapped_column(String(30))
    dedup_key: Mapped[str] = mapped_column(String(200), index=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|sent|deferred|failed|logged
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class SettingKV(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)


class DealFeedEntry(Base):
    __tablename__ = "deal_feed_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    feed: Mapped[str] = mapped_column(String(100))
    guid: Mapped[str] = mapped_column(String(500), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str | None] = mapped_column(String(2000))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    matched_item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"))
    match_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
