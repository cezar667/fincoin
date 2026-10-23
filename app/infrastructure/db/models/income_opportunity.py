import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin


class IncomeOpportunity(Base, TimestampMixin):
    __tablename__ = "income_opportunities"
    __table_args__ = (Index("ix_income_opportunities_user_stage", "user_id", "stage"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_monthly_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    setup_cost_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    hours_per_week: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    stage: Mapped[str] = mapped_column(
        String(24), nullable=False, default="IDEA", server_default="IDEA"
    )
    next_action: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
