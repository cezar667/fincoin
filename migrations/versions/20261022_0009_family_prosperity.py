"""add family prosperity planning

Revision ID: 20261022_0009
Revises: 20260313_0008
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20261022_0009"
down_revision = "20260313_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "debts",
        sa.Column(
            "current_balance_cents",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "debts",
        sa.Column(
            "minimum_payment_cents",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column("debts", sa.Column("creditor", sa.String(length=160), nullable=True))
    op.add_column("debts", sa.Column("due_day", sa.Integer(), nullable=True))
    op.add_column(
        "debts",
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="ACTIVE"
        ),
    )
    op.add_column("debts", sa.Column("notes", sa.Text(), nullable=True))
    op.execute(
        "UPDATE debts SET current_balance_cents = principal_cents WHERE current_balance_cents = 0"
    )

    op.create_table(
        "financial_goals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=140), nullable=False),
        sa.Column(
            "category", sa.String(length=30), nullable=False, server_default="OTHER"
        ),
        sa.Column("target_cents", sa.BigInteger(), nullable=False),
        sa.Column(
            "current_cents",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "monthly_contribution_cents",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column(
            "priority", sa.Integer(), nullable=False, server_default=sa.text("3")
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="ACTIVE"
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
    )
    op.create_index(
        "ix_financial_goals_user_status", "financial_goals", ["user_id", "status"]
    )

    op.create_table(
        "income_opportunities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "expected_monthly_cents",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "setup_cost_cents",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "hours_per_week", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("stage", sa.String(length=24), nullable=False, server_default="IDEA"),
        sa.Column("next_action", sa.String(length=255), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
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
    )
    op.create_index(
        "ix_income_opportunities_user_stage",
        "income_opportunities",
        ["user_id", "stage"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_income_opportunities_user_stage", table_name="income_opportunities"
    )
    op.drop_table("income_opportunities")
    op.drop_index("ix_financial_goals_user_status", table_name="financial_goals")
    op.drop_table("financial_goals")
    op.drop_column("debts", "notes")
    op.drop_column("debts", "status")
    op.drop_column("debts", "due_day")
    op.drop_column("debts", "creditor")
    op.drop_column("debts", "minimum_payment_cents")
    op.drop_column("debts", "current_balance_cents")
