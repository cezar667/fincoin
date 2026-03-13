"""themembers integration

Revision ID: 20260313_0006
Revises: 20260313_0005
Create Date: 2026-03-13 18:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260313_0006"
down_revision = "20260313_0005"
branch_labels = None
depends_on = None


integration_provider = sa.Enum("THEMEMBERS_CHECKOUT", name="integration_provider")
webhook_event_status = sa.Enum("RECEIVED", "PROCESSED", "IGNORED", "FAILED", name="webhook_event_status")


def _column_names(inspector, table_name: str) -> set[str]:
    return {item["name"] for item in inspector.get_columns(table_name)}


def _unique_names(inspector, table_name: str) -> set[str]:
    unique_constraints = {item["name"] for item in inspector.get_unique_constraints(table_name) if item.get("name")}
    unique_indexes = {item["name"] for item in inspector.get_indexes(table_name) if item.get("unique")}
    return unique_constraints | unique_indexes


def _index_names(inspector, table_name: str) -> set[str]:
    return {item["name"] for item in inspector.get_indexes(table_name) if item.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for temp_table in sorted(name for name in existing_tables if name.startswith("_alembic_tmp_")):
        op.execute(sa.text(f'DROP TABLE "{temp_table}"'))
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    dialect_name = bind.dialect.name
    integration_provider.create(bind, checkfirst=True)
    webhook_event_status.create(bind, checkfirst=True)

    if "business_integrations" not in existing_tables:
        op.create_table(
            "business_integrations",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("provider", integration_provider, nullable=False),
            sa.Column("display_name", sa.String(length=80), nullable=False),
            sa.Column("webhook_path_token", sa.String(length=80), nullable=False),
            sa.Column("webhook_secret_hash", sa.String(length=64), nullable=False),
            sa.Column("webhook_secret_hint", sa.String(length=12), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("business_id", "provider", name="uq_business_integrations_business_provider"),
            sa.UniqueConstraint("webhook_path_token", name="uq_business_integrations_webhook_path_token"),
        )
        op.create_index(
            "ix_business_integrations_business_active",
            "business_integrations",
            ["business_id", "is_active"],
        )

    if "webhook_events" not in existing_tables:
        op.create_table(
            "webhook_events",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column(
                "business_integration_id",
                sa.Uuid(),
                sa.ForeignKey("business_integrations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("provider", integration_provider, nullable=False),
            sa.Column("event_type", sa.String(length=120), nullable=False),
            sa.Column("event_key", sa.String(length=255), nullable=False),
            sa.Column("external_event_id", sa.String(length=120), nullable=True),
            sa.Column("status", webhook_event_status, nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("headers", sa.JSON(), nullable=False),
            sa.Column("body_sha256", sa.String(length=64), nullable=False),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("request_id", sa.String(length=64), nullable=True),
            sa.Column("source_ip", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=255), nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("business_integration_id", "event_key", name="uq_webhook_events_integration_event_key"),
        )
        op.create_index("ix_webhook_events_business_created", "webhook_events", ["business_id", "created_at"])
        op.create_index(
            "ix_webhook_events_integration_status",
            "webhook_events",
            ["business_integration_id", "status"],
        )

    member_columns = _column_names(inspector, "members")
    member_uniques = _unique_names(inspector, "members")
    if "external_customer_id" not in member_columns:
        op.add_column("members", sa.Column("external_customer_id", sa.String(length=120), nullable=True))
    if "uq_members_business_external_customer" not in member_uniques:
        if dialect_name == "sqlite":
            op.create_index(
                "uq_members_business_external_customer",
                "members",
                ["business_id", "external_customer_id"],
                unique=True,
            )
        else:
            op.create_unique_constraint(
                "uq_members_business_external_customer",
                "members",
                ["business_id", "external_customer_id"],
            )

    plan_columns = _column_names(inspector, "membership_plans")
    plan_uniques = _unique_names(inspector, "membership_plans")
    if "external_product_id" not in plan_columns:
        op.add_column("membership_plans", sa.Column("external_product_id", sa.String(length=120), nullable=True))
    if "external_reference_id" not in plan_columns:
        op.add_column("membership_plans", sa.Column("external_reference_id", sa.String(length=120), nullable=True))
    if "uq_membership_plans_business_external_product" not in plan_uniques:
        if dialect_name == "sqlite":
            op.create_index(
                "uq_membership_plans_business_external_product",
                "membership_plans",
                ["business_id", "external_product_id"],
                unique=True,
            )
        else:
            op.create_unique_constraint(
                "uq_membership_plans_business_external_product",
                "membership_plans",
                ["business_id", "external_product_id"],
            )
    if "uq_membership_plans_business_external_reference" not in plan_uniques:
        if dialect_name == "sqlite":
            op.create_index(
                "uq_membership_plans_business_external_reference",
                "membership_plans",
                ["business_id", "external_reference_id"],
                unique=True,
            )
        else:
            op.create_unique_constraint(
                "uq_membership_plans_business_external_reference",
                "membership_plans",
                ["business_id", "external_reference_id"],
            )

    subscription_columns = _column_names(inspector, "subscriptions")
    subscription_uniques = _unique_names(inspector, "subscriptions")
    if "external_subscription_id" not in subscription_columns:
        op.add_column("subscriptions", sa.Column("external_subscription_id", sa.String(length=120), nullable=True))
    if "cancel_requested_at" not in subscription_columns:
        op.add_column("subscriptions", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
    if "uq_subscriptions_business_external_subscription" not in subscription_uniques:
        if dialect_name == "sqlite":
            op.create_index(
                "uq_subscriptions_business_external_subscription",
                "subscriptions",
                ["business_id", "external_subscription_id"],
                unique=True,
            )
        else:
            op.create_unique_constraint(
                "uq_subscriptions_business_external_subscription",
                "subscriptions",
                ["business_id", "external_subscription_id"],
            )

    receivable_columns = _column_names(inspector, "receivables")
    receivable_uniques = _unique_names(inspector, "receivables")
    receivable_indexes = _index_names(inspector, "receivables")
    if "external_invoice_id" not in receivable_columns:
        op.add_column("receivables", sa.Column("external_invoice_id", sa.String(length=120), nullable=True))
    if "external_order_id" not in receivable_columns:
        op.add_column("receivables", sa.Column("external_order_id", sa.String(length=120), nullable=True))
    if "uq_receivables_business_external_invoice" not in receivable_uniques:
        if dialect_name == "sqlite":
            op.create_index(
                "uq_receivables_business_external_invoice",
                "receivables",
                ["business_id", "external_invoice_id"],
                unique=True,
            )
        else:
            op.create_unique_constraint(
                "uq_receivables_business_external_invoice",
                "receivables",
                ["business_id", "external_invoice_id"],
            )
    if "ix_receivables_business_external_order" not in receivable_indexes:
        op.create_index(
            "ix_receivables_business_external_order",
            "receivables",
            ["business_id", "external_order_id"],
        )

    receipt_columns = _column_names(inspector, "receipts")
    receipt_uniques = _unique_names(inspector, "receipts")
    if "external_transaction_id" not in receipt_columns:
        op.add_column("receipts", sa.Column("external_transaction_id", sa.String(length=120), nullable=True))
    if "uq_receipts_business_external_transaction" not in receipt_uniques:
        if dialect_name == "sqlite":
            op.create_index(
                "uq_receipts_business_external_transaction",
                "receipts",
                ["business_id", "external_transaction_id"],
                unique=True,
            )
        else:
            op.create_unique_constraint(
                "uq_receipts_business_external_transaction",
                "receipts",
                ["business_id", "external_transaction_id"],
            )


def downgrade() -> None:
    dialect_name = op.get_bind().dialect.name
    if dialect_name == "sqlite":
        op.drop_index("uq_receipts_business_external_transaction", table_name="receipts")
        op.drop_index("ix_receivables_business_external_order", table_name="receivables")
        op.drop_index("uq_receivables_business_external_invoice", table_name="receivables")
        op.drop_index("uq_subscriptions_business_external_subscription", table_name="subscriptions")
        op.drop_index("uq_membership_plans_business_external_reference", table_name="membership_plans")
        op.drop_index("uq_membership_plans_business_external_product", table_name="membership_plans")
        op.drop_index("uq_members_business_external_customer", table_name="members")
    else:
        op.drop_constraint("uq_receipts_business_external_transaction", "receipts", type_="unique")
        op.drop_index("ix_receivables_business_external_order", table_name="receivables")
        op.drop_constraint("uq_receivables_business_external_invoice", "receivables", type_="unique")
        op.drop_constraint("uq_subscriptions_business_external_subscription", "subscriptions", type_="unique")
        op.drop_constraint("uq_membership_plans_business_external_reference", "membership_plans", type_="unique")
        op.drop_constraint("uq_membership_plans_business_external_product", "membership_plans", type_="unique")
        op.drop_constraint("uq_members_business_external_customer", "members", type_="unique")

    op.drop_column("receipts", "external_transaction_id")
    op.drop_column("receivables", "external_order_id")
    op.drop_column("receivables", "external_invoice_id")
    op.drop_column("subscriptions", "cancel_requested_at")
    op.drop_column("subscriptions", "external_subscription_id")
    op.drop_column("membership_plans", "external_reference_id")
    op.drop_column("membership_plans", "external_product_id")
    op.drop_column("members", "external_customer_id")

    op.drop_index("ix_webhook_events_integration_status", table_name="webhook_events")
    op.drop_index("ix_webhook_events_business_created", table_name="webhook_events")
    op.drop_table("webhook_events")

    op.drop_index("ix_business_integrations_business_active", table_name="business_integrations")
    op.drop_table("business_integrations")

    webhook_event_status.drop(op.get_bind(), checkfirst=True)
    integration_provider.drop(op.get_bind(), checkfirst=True)
