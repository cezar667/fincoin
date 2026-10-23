import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin


class FinancialGoal(Base, TimestampMixin):
    __tablename__ = "financial_goals"
    __table_args__ = (Index("ix_financial_goals_user_status", "user_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    category: Mapped[str] = mapped_column(
        String(30), nullable=False, default="OTHER", server_default="OTHER"
    )
    target_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    current_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    monthly_contribution_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text("3")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
