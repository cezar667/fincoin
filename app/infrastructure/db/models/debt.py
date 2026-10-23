import uuid
from datetime import date

from sqlalchemy import (
    BigInteger,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin
from app.infrastructure.db.models.enums import DebtKind


class Debt(Base, TimestampMixin):
    __tablename__ = "debts"
    __table_args__ = (Index("ix_debts_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[DebtKind] = mapped_column(
        Enum(DebtKind, name="debt_kind"), nullable=False
    )
    principal_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    current_balance_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    minimum_payment_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    interest_apr_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_month: Mapped[date] = mapped_column(Date, nullable=False)
    creditor: Mapped[str | None] = mapped_column(String(160), nullable=True)
    due_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
