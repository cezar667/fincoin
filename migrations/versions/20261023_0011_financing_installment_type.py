"""add financing as an installment type

Revision ID: 20261023_0011
Revises: 20261022_0010
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261023_0011"
down_revision = "20261022_0010"
branch_labels = None
depends_on = None

installment_kind = postgresql.ENUM(
    "PURCHASE", "FINANCING", name="installment_kind", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    installment_kind.create(bind, checkfirst=True)
    op.add_column(
        "installments",
        sa.Column(
            "kind",
            installment_kind,
            nullable=False,
            server_default="PURCHASE",
        ),
    )
    op.add_column(
        "installments", sa.Column("creditor", sa.String(length=160), nullable=True)
    )
    op.add_column(
        "installments",
        sa.Column("financed_amount_cents", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "installments", sa.Column("interest_apr_bps", sa.Integer(), nullable=True)
    )
    op.add_column("installments", sa.Column("due_day", sa.Integer(), nullable=True))
    op.alter_column("installments", "credit_card_id", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM installments WHERE kind = 'FINANCING'")
    op.alter_column("installments", "credit_card_id", nullable=False)
    op.drop_column("installments", "due_day")
    op.drop_column("installments", "interest_apr_bps")
    op.drop_column("installments", "financed_amount_cents")
    op.drop_column("installments", "creditor")
    op.drop_column("installments", "kind")
    installment_kind.drop(op.get_bind(), checkfirst=True)
