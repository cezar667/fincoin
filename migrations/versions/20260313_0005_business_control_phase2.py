"""add business control phase 2

Revision ID: 20260313_0005
Revises: 20260313_0004
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa

revision = "20260313_0005"
down_revision = "20260313_0004"
branch_labels = None
depends_on = None

member_status = sa.Enum(
    "LEAD",
    "ACTIVE",
    "SUSPENDED",
    "BLOCKED",
    "CANCELED",
    name="member_status",
)
billing_cadence = sa.Enum("MONTHLY", name="billing_cadence")
subscription_status = sa.Enum(
    "ACTIVE",
    "SUSPENDED",
    "BLOCKED",
    "CANCELED",
    name="subscription_status",
)
receivable_status = sa.Enum(
    "PLANNED",
    "ISSUED",
    "PAID",
    "OVERDUE",
    "CANCELED",
    "RENEGOTIATED",
    "REFUNDED",
    name="receivable_status",
)
receivable_kind = sa.Enum(
    "ACTIVATION",
    "RECURRING",
    "REPLACEMENT",
    "ADJUSTMENT",
    name="receivable_kind",
)
receipt_method = sa.Enum(
    "PIX",
    "BOLETO",
    "CARD",
    "CASH",
    "TRANSFER",
    "OTHER",
    name="receipt_method",
)


def upgrade() -> None:
    bind = op.get_bind()
    member_status.create(bind, checkfirst=True)
    billing_cadence.create(bind, checkfirst=True)
    subscription_status.create(bind, checkfirst=True)
    receivable_status.create(bind, checkfirst=True)
    receivable_kind.create(bind, checkfirst=True)
    receipt_method.create(bind, checkfirst=True)

    op.create_table(
        "members",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("document_number", sa.String(40), nullable=True),
        sa.Column("status", member_status, nullable=False),
        sa.Column("joined_on", sa.Date(), nullable=False),
        sa.Column("activated_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_members_business_status", "members", ["business_id", "status"])
    op.create_index("ix_members_business_joined", "members", ["business_id", "joined_on"])

    op.create_table(
        "membership_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(140), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("cadence", billing_cadence, nullable=False),
        sa.Column("recurring_amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("activation_fee_cents", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("billing_day", sa.Integer(), nullable=False),
        sa.Column("grace_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("business_id", "name", name="uq_membership_plans_business_name"),
    )
    op.create_index("ix_membership_plans_business_active", "membership_plans", ["business_id", "is_active"])

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_id", sa.Uuid(), sa.ForeignKey("members.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("membership_plan_id", sa.Uuid(), sa.ForeignKey("membership_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", subscription_status, nullable=False),
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column("next_billing_on", sa.Date(), nullable=False),
        sa.Column("price_override_cents", sa.BigInteger(), nullable=True),
        sa.Column("canceled_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_subscriptions_business_status", "subscriptions", ["business_id", "status"])
    op.create_index("ix_subscriptions_member_status", "subscriptions", ["member_id", "status"])
    op.create_index("ix_subscriptions_business_next_billing", "subscriptions", ["business_id", "next_billing_on"])

    op.create_table(
        "receivables",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_id", sa.Uuid(), sa.ForeignKey("members.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), sa.ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("kind", receivable_kind, nullable=False),
        sa.Column("status", receivable_status, nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("discount_cents", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("competency_month", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint(
            "subscription_id",
            "kind",
            "competency_month",
            name="uq_receivables_subscription_kind_competency",
        ),
    )
    op.create_index("ix_receivables_business_status_due", "receivables", ["business_id", "status", "due_on"])
    op.create_index("ix_receivables_member_due", "receivables", ["member_id", "due_on"])

    op.create_table(
        "receipts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("receivable_id", sa.Uuid(), sa.ForeignKey("receivables.id", ondelete="CASCADE"), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("amount_received_cents", sa.BigInteger(), nullable=False),
        sa.Column("method", receipt_method, nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_receipts_business_received", "receipts", ["business_id", "received_on"])
    op.create_index("ix_receipts_receivable_received", "receipts", ["receivable_id", "received_on"])


def downgrade() -> None:
    op.drop_index("ix_receipts_receivable_received", table_name="receipts")
    op.drop_index("ix_receipts_business_received", table_name="receipts")
    op.drop_table("receipts")

    op.drop_index("ix_receivables_member_due", table_name="receivables")
    op.drop_index("ix_receivables_business_status_due", table_name="receivables")
    op.drop_table("receivables")

    op.drop_index("ix_subscriptions_business_next_billing", table_name="subscriptions")
    op.drop_index("ix_subscriptions_member_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_business_status", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_index("ix_membership_plans_business_active", table_name="membership_plans")
    op.drop_table("membership_plans")

    op.drop_index("ix_members_business_joined", table_name="members")
    op.drop_index("ix_members_business_status", table_name="members")
    op.drop_table("members")

    bind = op.get_bind()
    receipt_method.drop(bind, checkfirst=True)
    receivable_kind.drop(bind, checkfirst=True)
    receivable_status.drop(bind, checkfirst=True)
    subscription_status.drop(bind, checkfirst=True)
    billing_cadence.drop(bind, checkfirst=True)
    member_status.drop(bind, checkfirst=True)
