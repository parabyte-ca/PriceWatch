"""llm match cache

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-16 01:00:00
"""
import sqlalchemy as sa

from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'llm_match_cache',
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('same_product', sa.Boolean(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('reason', sa.String(length=300), nullable=True),
        sa.Column('model', sa.String(length=60), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade() -> None:
    op.drop_table('llm_match_cache')
