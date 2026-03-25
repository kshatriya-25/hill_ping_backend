"""add commission_override and commission_type to properties

Revision ID: d82500cdc1b4
Revises: b7e2f1a3c8d9
Create Date: 2026-03-25 20:38:03.049579

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd82500cdc1b4'
down_revision: Union[str, None] = 'b7e2f1a3c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add commission_override if not exists (may have been added manually)
    conn = op.get_bind()
    columns = [c['name'] for c in sa.inspect(conn).get_columns('properties')]
    if 'commission_override' not in columns:
        op.add_column('properties', sa.Column('commission_override', sa.Float(), nullable=True))
    op.add_column('properties', sa.Column('commission_type', sa.String(length=10), server_default='percentage', nullable=False))


def downgrade() -> None:
    op.drop_column('properties', 'commission_type')
    op.drop_column('properties', 'commission_override')
