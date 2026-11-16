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


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str | None] = mapped_column(String(300))
    api_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")  # admin | member
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WishList(Base):
    __tablename__ = "lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    occasion: Mapped[str | None] = mapped_column(String(120))
    recipient: Mapped[str | None] = mapped_column(String(120))
    event_date: Mapped[date | None] = mapped_column(Date)
    budget_cents: Mapped[int | None] = mapped_column(Integer)
    # read-only link for family (no account): /shared/<token>; None = not shared
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    share_show_bought: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    members: Mapped[list["ListMember"]] = relationship(back_populates="list", cascade="all, delete-orphan")


class ListMember(Base):
    __tablename__ = "list_members"
    __table_args__ = (UniqueConstraint("list_id", "user_id", name="uq_list_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("lists.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="editor")  # owner | editor | viewer
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    list: Mapped[WishList] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class ListInvite(Base):
    __tablename__ = "list_invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("lists.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(20), default="editor")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime)


class UserSetting(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)


class UserItemPref(Base):
    """Per-person preferences on an item (shared items keep separate snoozes)."""

    __tablename__ = "user_item_prefs"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime)
    muted: Mapped[bool] = mapped_column(Boolean, default=False)


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int | None] = mapped_column(ForeignKey("lists.id", ondelete="CASCADE"), index=True)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
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
    search_query: Mapped[str | None] = mapped_column(String(300))
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime)
    autofill: Mapped[bool] = mapped_column(Boolean, default=False)
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
    fetch_mode: Mapped[str] = mapped_column(String(20), default="auto")  # auto | search | manual
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
    consecutive_blocks: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PricePolicy(Base):
    """Price match and price protection terms per retailer. Data, not code: editable in the UI."""

    __tablename__ = "price_policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(200), unique=True)
    competitor_match: Mapped[bool] = mapped_column(Boolean, default=False)
    own_price_adjustment: Mapped[bool] = mapped_column(Boolean, default=False)
    window_days: Mapped[int | None] = mapped_column(Integer)
    member_window_days: Mapped[int | None] = mapped_column(Integer)
    electronics_window_days: Mapped[int | None] = mapped_column(Integer)
    excluded_events: Mapped[list | None] = mapped_column(JSON)
    excludes_marketplace: Mapped[bool] = mapped_column(Boolean, default=True)
    excludes_open_box: Mapped[bool] = mapped_column(Boolean, default=True)
    event_guarantee: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


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
    match_reasons: Mapped[dict | None] = mapped_column(JSON)
    discovered_via: Mapped[str | None] = mapped_column(String(30))
    fetch_mode: Mapped[str | None] = mapped_column(String(20))  # overrides retailer when set
    channel: Mapped[str] = mapped_column(String(40), default="online")  # online|warehouse|store:<id>|province:<code>
    external_id: Mapped[str | None] = mapped_column(String(100))  # reserved for external ids
    last_condition: Mapped[str | None] = mapped_column(String(20))
    last_seller_type: Mapped[str | None] = mapped_column(String(120))
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
    method: Mapped[str] = mapped_column(String(20), default="http")  # http|claude|search|manual|not_modified
    channel: Mapped[str] = mapped_column(String(40), default="online")
    seller_type: Mapped[str] = mapped_column(String(120), default="first_party")  # first_party | marketplace:<name>
    condition: Mapped[str] = mapped_column(String(20), default="new")  # new|open_box|refurbished|used
    coupon_cents: Mapped[int | None] = mapped_column(Integer)
    parse_confidence: Mapped[float | None] = mapped_column(Float)


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
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
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


class SerpSearch(Base):
    __tablename__ = "serp_searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    query: Mapped[str] = mapped_column(String(300), index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    billable: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[list | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)


class Purchase(Base):
    """Something a person bought; watched for claimable price drops during its protection window."""

    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_link_id: Mapped[int | None] = mapped_column(ForeignKey("source_links.id", ondelete="SET NULL"))
    retailer_domain: Mapped[str | None] = mapped_column(String(200))
    retailer_name: Mapped[str] = mapped_column(String(200))
    channel: Mapped[str] = mapped_column(String(40), default="online")
    price_cents: Mapped[int] = mapped_column(Integer)
    shipping_cents: Mapped[int | None] = mapped_column(Integer)
    purchased_on: Mapped[date] = mapped_column(Date)
    protection_days: Mapped[int] = mapped_column(Integer, default=0)
    protection_until: Mapped[date | None] = mapped_column(Date, index=True)
    protection_basis: Mapped[str | None] = mapped_column(String(200))
    badged: Mapped[bool] = mapped_column(Boolean, default=False)
    order_ref: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    lowest_seen_cents: Mapped[int | None] = mapped_column(Integer)
    lowest_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="watching")  # watching|claimable|claimed|expired|closed
    claimed_cents: Mapped[int | None] = mapped_column(Integer)
    reference_cents: Mapped[int | None] = mapped_column(Integer)  # 60-day median price when bought (for savings)
    reference_basis: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProofCapture(Base):
    """Evidence captured when a claimable drop was seen: page snapshot, hash, timestamps."""

    __tablename__ = "proof_captures"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id", ondelete="CASCADE"), index=True)
    observation_id: Mapped[int | None] = mapped_column(ForeignKey("observations.id", ondelete="SET NULL"))
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    url: Mapped[str] = mapped_column(String(2000))
    price_cents: Mapped[int] = mapped_column(Integer)
    seller: Mapped[str | None] = mapped_column(String(200))
    page_sha256: Mapped[str | None] = mapped_column(String(64))
    path: Mapped[str | None] = mapped_column(String(500))  # folder under data/artifacts
    screenshot: Mapped[bool] = mapped_column(Boolean, default=False)


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
    retailer_domain: Mapped[str | None] = mapped_column(String(200))
    deal_url: Mapped[str | None] = mapped_column(String(2000))
    matched_source_id: Mapped[int | None] = mapped_column(ForeignKey("source_links.id", ondelete="SET NULL"))
    price_cents: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[dict | None] = mapped_column(JSON)  # crowd signals from the thread's comments
    summary_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RetailerPerk(Base):
    """Cash-back portals, discounted gift cards and card offers that stack on a store's price (entered by hand)."""

    __tablename__ = "retailer_perks"

    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_domain: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # cashback | giftcard | card | other
    label: Mapped[str] = mapped_column(String(120))
    percent: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(500))
    valid_until: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    failures: Mapped[int] = mapped_column(Integer, default=0)


class FlyerMatch(Base):
    """A flyer (weekly ad) item matched to a wishlist item. Hints only, like forum threads."""

    __tablename__ = "flyer_matches"
    __table_args__ = (UniqueConstraint("item_id", "flyer_item_id", name="uq_flyer_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    flyer_item_id: Mapped[str] = mapped_column(String(100))
    merchant: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(500))
    price_cents: Mapped[int | None] = mapped_column(Integer)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime)
    postal_code: Mapped[str | None] = mapped_column(String(10))
    score: Mapped[float | None] = mapped_column(Float)
    url: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MarketOffer(Base):
    """The latest price each store shows for an item in search results (Google Shopping or Claude web search).

    Replaced on every search, so it is a snapshot, not a history. Tracked store pages keep their own history.
    """

    __tablename__ = "market_offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    merchant: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(500))
    price_cents: Mapped[int] = mapped_column(Integer)
    shipping_cents: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(String(1000))
    store_link: Mapped[bool] = mapped_column(Boolean, default=False)  # False: a Google Shopping page
    provider: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[float | None] = mapped_column(Float)
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    domain: Mapped[str | None] = mapped_column(String(120))  # the known Canadian store, when recognised
    kind: Mapped[str] = mapped_column(String(20), default="store")  # store | marketplace | bundle | other


class ListingFeedback(Base):
    """A household's one-tap correction: this search listing is not the product ("wrong")."""

    __tablename__ = "listing_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(String(300), index=True)  # lower-cased search text
    url: Mapped[str] = mapped_column(String(1000))
    merchant: Mapped[str | None] = mapped_column(String(120))
    verdict: Mapped[str] = mapped_column(String(20), default="wrong")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DealCategory(Base):
    """A kind of product someone wants deals on ("TVs", "kitchen accessories"), not a specific item."""

    __tablename__ = "deal_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    min_discount_pct: Mapped[int] = mapped_column(Integer, default=20)
    max_price_cents: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_search_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CategoryDeal(Base):
    """A deal found for a category: from the RedFlagDeals feed or a Google Shopping "on sale" search."""

    __tablename__ = "category_deals"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("deal_categories.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(1000))
    store: Mapped[str | None] = mapped_column(String(120))
    price_cents: Mapped[int | None] = mapped_column(Integer)
    was_cents: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(30))  # rfd | google_shopping
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def discount_pct(self) -> int | None:
        if self.price_cents and self.was_cents and self.was_cents > self.price_cents:
            return round((self.was_cents - self.price_cents) * 100 / self.was_cents)
        return None


class LlmMatchCache(Base):
    """Cached Claude answers to "same product?" for one item description and one listing title."""

    __tablename__ = "llm_match_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of model + item spec + listing title
    same_product: Mapped[bool] = mapped_column(Boolean)
    confidence: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(String(300))
    model: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EmailImport(Base):
    """One order-confirmation email read from the import mailbox, and what PriceWatch made of it."""

    __tablename__ = "email_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(String(300), unique=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str | None] = mapped_column(String(300))
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    retailer_domain: Mapped[str | None] = mapped_column(String(200))
    order_ref: Mapped[str | None] = mapped_column(String(60))
    method: Mapped[str] = mapped_column(String(20), default="rules")  # rules | claude
    lines: Mapped[list | None] = mapped_column(JSON)  # [{name, price_cents, quantity, item_id, purchase_id}]
    status: Mapped[str] = mapped_column(String(20), default="new")  # recorded | partial | unmatched | ignored | error
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
