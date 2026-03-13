"""add business control phase 1

Revision ID: 20260313_0004
Revises: 20260311_0003
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa

revision = "20260313_0004"
down_revision = "20260311_0003"
branch_labels = None
depends_on = None

business_account_type = sa.Enum(
    "CASH",
    "BANK",
    "DIGITAL_WALLET",
    "RECEIVABLE",
    name="business_account_type",
)
business_category_kind = sa.Enum(
    "RECURRING_REVENUE",
    "NON_RECURRING_REVENUE",
    "DEDUCTION",
    "REFUND",
    "DISCOUNT",
    "DIRECT_COST",
    "OPERATING_EXPENSE",
    "ADMIN_EXPENSE",
    "FINANCIAL_EXPENSE",
    "INVESTMENT",
    "TAX",
    name="business_category_kind",
)
audit_action = sa.Enum(
    "CREATE",
    "UPDATE",
    "ACTIVATE",
    "DEACTIVATE",
    "SWITCH",
    name="audit_action",
)


def upgrade() -> None:
    bind = op.get_bind()
    business_account_type.create(bind, checkfirst=True)
    business_category_kind.create(bind, checkfirst=True)
    audit_action.create(bind, checkfirst=True)

    op.create_table(
        "businesses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("legal_name", sa.String(180), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="BRL"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("slug", name="uq_businesses_slug"),
    )
    op.create_index("ix_businesses_owner_active", "businesses", ["owner_user_id", "is_active"])

    op.create_table(
        "business_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(140), nullable=False),
        sa.Column("type", business_account_type, nullable=False),
        sa.Column("institution_name", sa.String(140), nullable=True),
        sa.Column("initial_balance_cents", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("business_id", "name", name="uq_business_accounts_business_name"),
    )
    op.create_index("ix_business_accounts_business_active", "business_accounts", ["business_id", "is_active"])

    op.create_table(
        "business_categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(40), nullable=True),
        sa.Column("name", sa.String(140), nullable=False),
        sa.Column("kind", business_category_kind, nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("business_id", "name", name="uq_business_categories_business_name"),
    )
    op.create_index("ix_business_categories_business_kind", "business_categories", ["business_id", "kind"])

    op.create_table(
        "cost_centers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(40), nullable=True),
        sa.Column("name", sa.String(140), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("business_id", "name", name="uq_cost_centers_business_name"),
        sa.UniqueConstraint("business_id", "code", name="uq_cost_centers_business_code"),
    )
    op.create_index("ix_cost_centers_business_active", "cost_centers", ["business_id", "is_active"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", audit_action, nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.String(255), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_audit_logs_business_created", "audit_logs", ["business_id", "created_at"])
    op.create_index("ix_audit_logs_actor_created", "audit_logs", ["actor_user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_actor_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_business_created", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_cost_centers_business_active", table_name="cost_centers")
    op.drop_table("cost_centers")

    op.drop_index("ix_business_categories_business_kind", table_name="business_categories")
    op.drop_table("business_categories")

    op.drop_index("ix_business_accounts_business_active", table_name="business_accounts")
    op.drop_table("business_accounts")

    op.drop_index("ix_businesses_owner_active", table_name="businesses")
    op.drop_table("businesses")

    bind = op.get_bind()
    audit_action.drop(bind, checkfirst=True)
    business_category_kind.drop(bind, checkfirst=True)
    business_account_type.drop(bind, checkfirst=True)
