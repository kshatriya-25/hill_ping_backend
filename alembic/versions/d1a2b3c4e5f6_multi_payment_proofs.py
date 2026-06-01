"""multiple payment proofs (payment_proof_urls JSON array)

Revision ID: d1a2b3c4e5f6
Revises: c1d2e3f4a5b6
Create Date: 2026-06-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1a2b3c4e5f6"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, additive — stores a JSON array of all uploaded proof URLs.
    # payment_proof_url is kept (first proof) for backward compatibility.
    op.add_column("bookings", sa.Column("payment_proof_urls", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bookings", "payment_proof_urls")
