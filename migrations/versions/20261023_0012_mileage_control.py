"""add mileage control

Revision ID: 20261023_0012
Revises: 20261023_0011
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_0012"
down_revision = "20261023_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    programs_created = "mileage_programs" not in tables
    if programs_created:
        op.create_table(
            "mileage_programs",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column(
                "balance_miles",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("target_miles", sa.Integer(), nullable=True),
            sa.Column("expires_on", sa.Date(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
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
    program_indexes = (
        set()
        if programs_created
        else {item["name"] for item in inspector.get_indexes("mileage_programs")}
    )
    if "ix_mileage_programs_user_expiry" not in program_indexes:
        op.create_index(
            "ix_mileage_programs_user_expiry",
            "mileage_programs",
            ["user_id", "expires_on"],
        )
    movements_created = "mileage_movements" not in tables
    if movements_created:
        op.create_table(
            "mileage_movements",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "program_id",
                sa.Uuid(),
                sa.ForeignKey("mileage_programs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("miles", sa.Integer(), nullable=False),
            sa.Column("occurred_on", sa.Date(), nullable=False),
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
    movement_indexes = (
        set()
        if movements_created
        else {item["name"] for item in inspector.get_indexes("mileage_movements")}
    )
    if "ix_mileage_movements_program_date" not in movement_indexes:
        op.create_index(
            "ix_mileage_movements_program_date",
            "mileage_movements",
            ["program_id", "occurred_on"],
        )


def downgrade() -> None:
    op.drop_index("ix_mileage_movements_program_date", table_name="mileage_movements")
    op.drop_table("mileage_movements")
    op.drop_index("ix_mileage_programs_user_expiry", table_name="mileage_programs")
    op.drop_table("mileage_programs")
