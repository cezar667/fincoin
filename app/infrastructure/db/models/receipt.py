import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin
from app.infrastructure.db.models.enums import ReceiptMethod


class Receipt(Base, TimestampMixin):
    __tablename__ = "receipts"
    __table_args__ = (
        Index("ix_receipts_business_received", "business_id", "received_on"),
        Index("ix_receipts_receivable_received", "receivable_id", "received_on"),
        UniqueConstraint("business_id", "external_transaction_id", name="uq_receipts_business_external_transaction"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
    )
    receivable_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("receivables.id", ondelete="CASCADE"),
        nullable=False,
    )
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount_received_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    external_transaction_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    method: Mapped[ReceiptMethod] = mapped_column(Enum(ReceiptMethod, name="receipt_method"), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    business = relationship("Business", back_populates="receipts")
    receivable = relationship("Receivable", back_populates="receipts")
