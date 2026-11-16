"""listing feedback, deal categories and category deals

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-16 20:00:00
"""
import sqlalchemy as sa

from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'listing_feedback',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('item_id', sa.Integer(), sa.ForeignKey('items.id', ondelete='CASCADE'), nullable=True),
        sa.Column('query', sa.String(length=300), nullable=False),
        sa.Column('url', sa.String(length=1000), nullable=False),
        sa.Column('merchant', sa.String(length=120), nullable=True),
        sa.Column('verdict', sa.String(length=20), nullable=False, server_default='wrong'),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_listing_feedback_item_id', 'listing_feedback', ['item_id'])
    op.create_index('ix_listing_feedback_query', 'listing_feedback', ['query'])
    op.create_table(
        'deal_categories',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('min_discount_pct', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('max_price_cents', sa.Integer(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_search_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_deal_categories_user_id', 'deal_categories', ['user_id'])
    op.create_table(
        'category_deals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('category_id', sa.Integer(), sa.ForeignKey('deal_categories.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('url', sa.String(length=1000), nullable=False),
        sa.Column('store', sa.String(length=120), nullable=True),
        sa.Column('price_cents', sa.Integer(), nullable=True),
        sa.Column('was_cents', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=30), nullable=False),
        sa.Column('seen_at', sa.DateTime(), nullable=False),
        sa.Column('dismissed', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index('ix_category_deals_category_id', 'category_deals', ['category_id'])
    op.create_index('ix_category_deals_seen_at', 'category_deals', ['seen_at'])


def downgrade() -> None:
    op.drop_table('category_deals')
    op.drop_table('deal_categories')
    op.drop_table('listing_feedback')
