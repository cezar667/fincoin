import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin
from app.infrastructure.db.models.enums import RecurringCadence, TransactionDirection


class RecurringRule(Base, TimestampMixin):
    __tablename__ = "recurring_rules"
    __table_args__ = (Index("ix_recurring_rules_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    direction: Mapped[TransactionDirection] = mapped_column(Enum(TransactionDirection, name="recurring_direction"), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    cadence: Mapped[RecurringCadence] = mapped_column(Enum(RecurringCadence, name="recurring_cadence"), nullable=False)
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False)
    start_month: Mapped[date] = mapped_column(Date, nullable=False)
    end_month: Mapped[date | None] = mapped_column(Date, nullable=True)

