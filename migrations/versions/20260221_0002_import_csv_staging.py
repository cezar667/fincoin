"""add import staging tables

Revision ID: 20260221_0002
Revises: 20260216_0001
Create Date: 2026-02-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260221_0002"
down_revision = "20260216_0001"
branch_labels = None
depends_on = None

import_file_status = sa.Enum("IMPORTED", "REVIEWING", "APPLIED", name="import_file_status")
external_transaction_review_status = sa.Enum(
    "PENDING",
    "APPROVED",
    "REJECTED",
    "APPLIED",
    name="external_transaction_review_status",
)
transaction_direction = sa.Enum("INCOME", "EXPENSE", name="transaction_direction", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        import_file_status.create(bind, checkfirst=True)
        external_transaction_review_status.create(bind, checkfirst=True)

    op.create_table(
        "import_files",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("status", import_file_status, nullable=False, server_default=sa.text("'IMPORTED'")),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_import_files_user_uploaded_at", "import_files", ["user_id", "uploaded_at"])

    op.create_table(
        "external_transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("import_file_id", sa.Uuid(), sa.ForeignKey("import_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("card_id", sa.Uuid(), sa.ForeignKey("credit_cards.id", ondelete="SET NULL"), nullable=True),
        sa.Column("raw_date", sa.Date(), nullable=False),
        sa.Column("raw_description", sa.String(length=255), nullable=False),
        sa.Column("raw_amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("normalized_date", sa.Date(), nullable=False),
        sa.Column("normalized_description", sa.String(length=255), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("direction", transaction_direction, nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column(
            "raw_row_json",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "review_status",
            external_transaction_review_status,
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("mapped_category_id", sa.Uuid(), sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("mapped_account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("user_id", "source", "hash", name="uq_external_transactions_user_source_hash"),
    )
    op.create_index(
        "ix_external_transactions_user_import_review",
        "external_transactions",
        ["user_id", "import_file_id", "review_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_external_transactions_user_import_review", table_name="external_transactions")
    op.drop_table("external_transactions")

    op.drop_index("ix_import_files_user_uploaded_at", table_name="import_files")
    op.drop_table("import_files")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        external_transaction_review_status.drop(bind, checkfirst=True)
        import_file_status.drop(bind, checkfirst=True)
