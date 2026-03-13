import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin


class Installment(Base, TimestampMixin):
    __tablename__ = "installments"
    __table_args__ = (
        Index("ix_installments_user_first_comp", "user_id", "first_competency_month"),
        Index("ix_installments_user_card", "user_id", "credit_card_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    credit_card_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("credit_cards.id", ondelete="RESTRICT"), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_parts: Mapped[int] = mapped_column(Integer, nullable=False)
    part_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_competency_month: Mapped[date] = mapped_column(Date, nullable=False)

