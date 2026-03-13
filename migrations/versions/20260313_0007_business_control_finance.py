"""business control finance

Revision ID: 20260313_0007
Revises: 20260313_0006
Create Date: 2026-03-13 20:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260313_0007"
down_revision = "20260313_0006"
branch_labels = None
depends_on = None


business_cash_activity_type = sa.Enum(
    "OPERATING",
    "INVESTING",
    "FINANCING",
    name="business_cash_activity_type",
)
funding_installment_status = sa.Enum(
    "OPEN",
    "PAID",
    "OVERDUE",
    name="funding_installment_status",
)
transaction_direction = sa.Enum("INCOME", "EXPENSE", name="transaction_direction")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    business_cash_activity_type.create(bind, checkfirst=True)
    funding_installment_status.create(bind, checkfirst=True)
    transaction_direction.create(bind, checkfirst=True)

    if "business_fundings" not in existing_tables:
        op.create_table(
            "business_fundings",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "disbursement_account_id",
                sa.Uuid(),
                sa.ForeignKey("business_accounts.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "settlement_account_id",
                sa.Uuid(),
                sa.ForeignKey("business_accounts.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "payment_category_id",
                sa.Uuid(),
                sa.ForeignKey("business_categories.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "cost_center_id",
                sa.Uuid(),
                sa.ForeignKey("cost_centers.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("lender_name", sa.String(length=160), nullable=True),
            sa.Column("principal_cents", sa.BigInteger(), nullable=False),
            sa.Column("installment_amount_cents", sa.BigInteger(), nullable=False),
            sa.Column("installment_count", sa.Integer(), nullable=False),
            sa.Column("annual_interest_bps", sa.Integer(), nullable=True),
            sa.Column("disbursed_on", sa.Date(), nullable=False),
            sa.Column("first_due_on", sa.Date(), nullable=False),
            sa.Column("notes", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_business_fundings_business_disbursed", "business_fundings", ["business_id", "disbursed_on"])
        op.create_index("ix_business_fundings_business_first_due", "business_fundings", ["business_id", "first_due_on"])

    if "business_cash_entries" not in existing_tables:
        op.create_table(
            "business_cash_entries",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "business_account_id",
                sa.Uuid(),
                sa.ForeignKey("business_accounts.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "business_category_id",
                sa.Uuid(),
                sa.ForeignKey("business_categories.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "cost_center_id",
                sa.Uuid(),
                sa.ForeignKey("cost_centers.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "funding_id",
                sa.Uuid(),
                sa.ForeignKey("business_fundings.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("activity_type", business_cash_activity_type, nullable=False),
            sa.Column("direction", transaction_direction, nullable=False),
            sa.Column("description", sa.String(length=255), nullable=False),
            sa.Column("amount_cents", sa.BigInteger(), nullable=False),
            sa.Column("occurred_on", sa.Date(), nullable=False),
            sa.Column("notes", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_business_cash_entries_business_date", "business_cash_entries", ["business_id", "occurred_on"])
        op.create_index(
            "ix_business_cash_entries_account_date",
            "business_cash_entries",
            ["business_account_id", "occurred_on"],
        )
        op.create_index(
            "ix_business_cash_entries_business_direction",
            "business_cash_entries",
            ["business_id", "direction"],
        )

    if "business_funding_installments" not in existing_tables:
        op.create_table(
            "business_funding_installments",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column(
                "funding_id",
                sa.Uuid(),
                sa.ForeignKey("business_fundings.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "payment_entry_id",
                sa.Uuid(),
                sa.ForeignKey("business_cash_entries.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("installment_number", sa.Integer(), nullable=False),
            sa.Column("due_on", sa.Date(), nullable=False),
            sa.Column("amount_due_cents", sa.BigInteger(), nullable=False),
            sa.Column("amount_paid_cents", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("paid_on", sa.Date(), nullable=True),
            sa.Column("status", funding_installment_status, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("funding_id", "installment_number", name="uq_business_funding_installments_number"),
            sa.UniqueConstraint("payment_entry_id", name="uq_business_funding_installments_payment_entry"),
        )
        op.create_index(
            "ix_business_funding_installments_business_due",
            "business_funding_installments",
            ["business_id", "due_on"],
        )
        op.create_index(
            "ix_business_funding_installments_business_status",
            "business_funding_installments",
            ["business_id", "status"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "business_funding_installments" in existing_tables:
        op.drop_index("ix_business_funding_installments_business_status", table_name="business_funding_installments")
        op.drop_index("ix_business_funding_installments_business_due", table_name="business_funding_installments")
        op.drop_table("business_funding_installments")

    if "business_cash_entries" in existing_tables:
        op.drop_index("ix_business_cash_entries_business_direction", table_name="business_cash_entries")
        op.drop_index("ix_business_cash_entries_account_date", table_name="business_cash_entries")
        op.drop_index("ix_business_cash_entries_business_date", table_name="business_cash_entries")
        op.drop_table("business_cash_entries")

    if "business_fundings" in existing_tables:
        op.drop_index("ix_business_fundings_business_first_due", table_name="business_fundings")
        op.drop_index("ix_business_fundings_business_disbursed", table_name="business_fundings")
        op.drop_table("business_fundings")

    funding_installment_status.drop(bind, checkfirst=True)
    business_cash_activity_type.drop(bind, checkfirst=True)
