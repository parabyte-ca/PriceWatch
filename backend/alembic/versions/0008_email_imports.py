"""email imports

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-16 02:00:00
"""
import sqlalchemy as sa

from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'email_imports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.String(length=300), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('subject', sa.String(length=300), nullable=True),
        sa.Column('received_at', sa.DateTime(), nullable=True),
        sa.Column('retailer_domain', sa.String(length=200), nullable=True),
        sa.Column('order_ref', sa.String(length=60), nullable=True),
        sa.Column('method', sa.String(length=20), nullable=False),
        sa.Column('lines', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id'),
    )
    with op.batch_alter_table('email_imports') as batch:
        batch.create_index('ix_email_imports_user_id', ['user_id'])


def downgrade() -> None:
    op.drop_table('email_imports')
