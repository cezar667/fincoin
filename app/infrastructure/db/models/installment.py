import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin
from app.infrastructure.db.models.enums import InstallmentKind


class Installment(Base, TimestampMixin):
    __tablename__ = "installments"
    __table_args__ = (
        Index("ix_installments_user_first_comp", "user_id", "first_competency_month"),
        Index("ix_installments_user_card", "user_id", "credit_card_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    credit_card_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("credit_cards.id", ondelete="RESTRICT"), nullable=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[InstallmentKind] = mapped_column(
        Enum(InstallmentKind, name="installment_kind"),
        nullable=False,
        default=InstallmentKind.PURCHASE,
        server_default=InstallmentKind.PURCHASE.value,
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    creditor: Mapped[str | None] = mapped_column(String(160), nullable=True)
    financed_amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    interest_apr_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_parts: Mapped[int] = mapped_column(Integer, nullable=False)
    part_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_competency_month: Mapped[date] = mapped_column(Date, nullable=False)
