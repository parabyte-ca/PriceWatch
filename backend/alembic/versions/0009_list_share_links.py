"""list share links

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-16 03:00:00
"""
import sqlalchemy as sa

from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('lists') as batch:
        batch.add_column(sa.Column('share_token', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('share_show_bought', sa.Boolean(), server_default=sa.true(), nullable=False))
        batch.create_unique_constraint('uq_lists_share_token', ['share_token'])


def downgrade() -> None:
    with op.batch_alter_table('lists') as batch:
        batch.drop_constraint('uq_lists_share_token', type_='unique')
        batch.drop_column('share_show_bought')
        batch.drop_column('share_token')
