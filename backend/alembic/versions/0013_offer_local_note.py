"""nearby-store note on market offers

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-16 21:00:00
"""
import sqlalchemy as sa

from alembic import op

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('market_offers') as batch:
        batch.add_column(sa.Column('local_note', sa.String(length=80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('market_offers') as batch:
        batch.drop_column('local_note')
