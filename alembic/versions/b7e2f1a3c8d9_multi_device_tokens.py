"""multi_device_tokens

Revision ID: b7e2f1a3c8d9
Revises: 393cb0a18d49
Create Date: 2026-03-22 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e2f1a3c8d9'
down_revision: Union[str, None] = '393cb0a18d49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'device_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('fcm_token', sa.String(length=500), nullable=False),
        sa.Column('device_name', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_device_tokens_id', 'device_tokens', ['id'])
    op.create_index('ix_device_tokens_user_id', 'device_tokens', ['user_id'])
    op.create_index('ix_device_tokens_fcm_token', 'device_tokens', ['fcm_token'], unique=True)
    op.create_index('ix_device_tokens_user_id_fcm', 'device_tokens', ['user_id', 'fcm_token'])

    # Migrate existing fcm_token values into device_tokens table
    op.execute("""
        INSERT INTO device_tokens (user_id, fcm_token, created_at, updated_at)
        SELECT id, fcm_token, NOW(), NOW()
        FROM users
        WHERE fcm_token IS NOT NULL AND fcm_token != ''
    """)


def downgrade() -> None:
    op.drop_table('device_tokens')
