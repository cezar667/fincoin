import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin
from app.infrastructure.db.models.enums import DebtKind


class Debt(Base, TimestampMixin):
    __tablename__ = "debts"
    __table_args__ = (Index("ix_debts_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[DebtKind] = mapped_column(Enum(DebtKind, name="debt_kind"), nullable=False)
    principal_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    interest_apr_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_month: Mapped[date] = mapped_column(Date, nullable=False)

