"""add financial plan tables

Revision ID: 20261030_0013
Revises: 20261023_0012
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op

revision = "20261030_0013"
down_revision = "20261023_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "financial_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
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
    op.create_index("ix_financial_plans_user_id", "financial_plans", ["user_id"])

    op.create_table(
        "plan_transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("financial_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            sa.Uuid(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
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
            "transaction_id", name="uq_plan_transactions_transaction_id"
        ),
    )
    op.create_index("ix_plan_transactions_plan_id", "plan_transactions", ["plan_id"])

    op.create_table(
        "plan_installments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("financial_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "installment_id",
            sa.Uuid(),
            sa.ForeignKey("installments.id", ondelete="CASCADE"),
            nullable=False,
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
            "installment_id", name="uq_plan_installments_installment_id"
        ),
    )
    op.create_index("ix_plan_installments_plan_id", "plan_installments", ["plan_id"])

    op.create_table(
        "plan_recurring_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("financial_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recurring_rule_id",
            sa.Uuid(),
            sa.ForeignKey("recurring_rules.id", ondelete="CASCADE"),
            nullable=False,
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
            "recurring_rule_id", name="uq_plan_recurring_rules_recurring_rule_id"
        ),
    )
    op.create_index(
        "ix_plan_recurring_rules_plan_id", "plan_recurring_rules", ["plan_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_plan_recurring_rules_plan_id", table_name="plan_recurring_rules")
    op.drop_table("plan_recurring_rules")
    op.drop_index("ix_plan_installments_plan_id", table_name="plan_installments")
    op.drop_table("plan_installments")
    op.drop_index("ix_plan_transactions_plan_id", table_name="plan_transactions")
    op.drop_table("plan_transactions")
    op.drop_index("ix_financial_plans_user_id", table_name="financial_plans")
    op.drop_table("financial_plans")
