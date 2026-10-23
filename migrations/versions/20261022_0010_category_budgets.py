"""add monthly category budgets

Revision ID: 20261022_0010
Revises: 20261022_0009
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20261022_0010"
down_revision = "20261022_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "category_budgets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "category_id",
            sa.Uuid(),
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("monthly_limit_cents", sa.BigInteger(), nullable=False),
        sa.Column(
            "alert_percent", sa.Integer(), nullable=False, server_default=sa.text("80")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "user_id", "category_id", name="uq_category_budgets_user_category"
        ),
    )
    op.create_index(
        "ix_category_budgets_user_active", "category_budgets", ["user_id", "is_active"]
    )


def downgrade() -> None:
    op.drop_index("ix_category_budgets_user_active", table_name="category_budgets")
    op.drop_table("category_budgets")
