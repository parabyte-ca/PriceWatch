"""deal category search options: adult (SafeSearch off), own search words, Claude web search

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-18 09:00:00
"""
import sqlalchemy as sa

from alembic import op

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('deal_categories') as batch:
        batch.add_column(sa.Column('adult', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('search_words', sa.String(length=500), nullable=True))
        batch.add_column(sa.Column('word_index', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('claude_search', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('last_claude_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('deal_categories') as batch:
        for col in ('last_claude_at', 'claude_search', 'word_index', 'search_words', 'adult'):
            batch.drop_column(col)
