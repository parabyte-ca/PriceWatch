"""v1: prices across stores; drop browser, Keepa and changedetection fetch modes

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-16 19:00:00
"""
import sqlalchemy as sa

from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('market_offers') as batch:
        batch.add_column(sa.Column('domain', sa.String(length=120), nullable=True))
        batch.add_column(sa.Column('kind', sa.String(length=20), nullable=False, server_default='store'))
    # stores that block automated visits now get prices from searches; the browser and Keepa are gone
    op.execute("UPDATE retailers SET fetch_mode = 'search' WHERE fetch_mode IN ('browser', 'keepa')")
    op.execute("UPDATE retailers SET fetch_mode = 'auto' WHERE fetch_mode IN ('http', 'bestbuy_api')")
    op.execute("UPDATE source_links SET fetch_mode = NULL WHERE fetch_mode IN ('http', 'browser', 'bestbuy_api')")
    op.execute("UPDATE source_links SET fetch_mode = 'search' WHERE fetch_mode IN ('keepa', 'changedetection')")


def downgrade() -> None:
    with op.batch_alter_table('market_offers') as batch:
        batch.drop_column('kind')
        batch.drop_column('domain')
