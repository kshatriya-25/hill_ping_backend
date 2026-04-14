"""room inventory, configurable weekends, mediator/platform per-night fees

Revision ID: f9a8b7c6d5e4
Revises: e3f4a5b6c7d8
Create Date: 2026-04-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f9a8b7c6d5e4"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rooms",
        sa.Column("total_rooms", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("rooms", sa.Column("weekend_days", sa.JSON(), nullable=True))
    op.add_column("rooms", sa.Column("mediator_commission", sa.Numeric(10, 2), nullable=True))
    op.add_column("rooms", sa.Column("platform_fee", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("rooms", "platform_fee")
    op.drop_column("rooms", "mediator_commission")
    op.drop_column("rooms", "weekend_days")
    op.drop_column("rooms", "total_rooms")
