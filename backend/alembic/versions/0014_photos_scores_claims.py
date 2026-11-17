"""product photos, deal scores and sightings, gift claims

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-16 22:00:00
"""
import sqlalchemy as sa

from alembic import op

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('market_offers') as batch:
        batch.add_column(sa.Column('image_url', sa.String(length=1000), nullable=True))
    with op.batch_alter_table('category_deals') as batch:
        batch.add_column(sa.Column('image_url', sa.String(length=1000), nullable=True))
        batch.add_column(sa.Column('score', sa.Integer(), nullable=True))
    with op.batch_alter_table('items') as batch:
        batch.add_column(sa.Column('claimed_by_user_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('claimed_by_name', sa.String(length=80), nullable=True))
        batch.add_column(sa.Column('claimed_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('claimed_code', sa.String(length=64), nullable=True))
        batch.create_foreign_key('fk_items_claimed_by_user', 'users', ['claimed_by_user_id'], ['id'], ondelete='SET NULL')
    op.create_table(
        'deal_sightings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('url_key', sa.String(length=64), nullable=False),
        sa.Column('price_cents', sa.Integer(), nullable=False),
        sa.Column('seen_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_deal_sightings_url_key', 'deal_sightings', ['url_key'])


def downgrade() -> None:
    op.drop_table('deal_sightings')
    with op.batch_alter_table('items') as batch:
        batch.drop_constraint('fk_items_claimed_by_user', type_='foreignkey')
        batch.drop_column('claimed_code')
        batch.drop_column('claimed_at')
        batch.drop_column('claimed_by_name')
        batch.drop_column('claimed_by_user_id')
    with op.batch_alter_table('category_deals') as batch:
        batch.drop_column('score')
        batch.drop_column('image_url')
    with op.batch_alter_table('market_offers') as batch:
        batch.drop_column('image_url')
