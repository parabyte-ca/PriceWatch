"""market offers (best price across stores from search results)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-16 17:00:00
"""
import sqlalchemy as sa

from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'market_offers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('item_id', sa.Integer(), sa.ForeignKey('items.id', ondelete='CASCADE'), nullable=False),
        sa.Column('merchant', sa.String(length=120), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('price_cents', sa.Integer(), nullable=False),
        sa.Column('shipping_cents', sa.Integer(), nullable=True),
        sa.Column('url', sa.String(length=1000), nullable=False),
        sa.Column('store_link', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('provider', sa.String(length=30), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('seen_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_market_offers_item_id', 'market_offers', ['item_id'])


def downgrade() -> None:
    op.drop_index('ix_market_offers_item_id', table_name='market_offers')
    op.drop_table('market_offers')
