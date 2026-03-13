"""add account initial balance

Revision ID: 20260311_0003
Revises: 20260221_0002
Create Date: 2026-03-11
"""

from alembic import op
import sqlalchemy as sa

revision = "20260311_0003"
down_revision = "20260221_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "initial_balance_cents",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("accounts", "initial_balance_cents")
