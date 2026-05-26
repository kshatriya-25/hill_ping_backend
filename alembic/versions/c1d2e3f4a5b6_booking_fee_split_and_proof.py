"""booking fee split (hotel/mediator/platform) + payment proof

Revision ID: c1d2e3f4a5b6
Revises: f9a8b7c6d5e4
Create Date: 2026-05-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "f9a8b7c6d5e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("hotel_fee", sa.Numeric(10, 2), nullable=True))
    op.add_column("bookings", sa.Column("mediator_fee", sa.Numeric(10, 2), nullable=True))
    op.add_column("bookings", sa.Column("platform_fee", sa.Numeric(10, 2), nullable=True))
    op.add_column("bookings", sa.Column("payment_proof_url", sa.String(length=255), nullable=True))
    op.add_column("bookings", sa.Column("payment_reference", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("bookings", "payment_reference")
    op.drop_column("bookings", "payment_proof_url")
    op.drop_column("bookings", "platform_fee")
    op.drop_column("bookings", "mediator_fee")
    op.drop_column("bookings", "hotel_fee")
