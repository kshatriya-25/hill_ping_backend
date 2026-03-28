"""payout_booking_id_nullable

Revision ID: e3f4a5b6c7d8
Revises: d82500cdc1b4
Create Date: 2026-03-28 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3f4a5b6c7d8'
down_revision: str = 'd82500cdc1b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('payouts', 'booking_id',
                     existing_type=sa.Integer(),
                     nullable=True)


def downgrade() -> None:
    # Set any NULL booking_ids to 0 before making non-nullable (safety)
    op.execute("UPDATE payouts SET booking_id = 0 WHERE booking_id IS NULL")
    op.alter_column('payouts', 'booking_id',
                     existing_type=sa.Integer(),
                     nullable=False)
