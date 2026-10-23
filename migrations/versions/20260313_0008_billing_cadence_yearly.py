"""allow yearly membership cadence

Revision ID: 20260313_0008
Revises: 20260313_0007
Create Date: 2026-03-13
"""

from alembic import op

revision = "20260313_0008"
down_revision = "20260313_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE billing_cadence ADD VALUE IF NOT EXISTS 'YEARLY'")


def downgrade() -> None:
    # PostgreSQL does not support dropping enum labels without rebuilding the type.
    # The application keeps backward compatibility with YEARLY values already stored.
    pass
