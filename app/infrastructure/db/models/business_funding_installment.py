import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, Enum, ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin
from app.infrastructure.db.models.enums import FundingInstallmentStatus


class BusinessFundingInstallment(Base, TimestampMixin):
    __tablename__ = "business_funding_installments"
    __table_args__ = (
        UniqueConstraint(
            "funding_id",
            "installment_number",
            name="uq_business_funding_installments_number",
        ),
        UniqueConstraint("payment_entry_id", name="uq_business_funding_installments_payment_entry"),
        Index("ix_business_funding_installments_business_due", "business_id", "due_on"),
        Index("ix_business_funding_installments_business_status", "business_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    funding_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("business_fundings.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
    )
    payment_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("business_cash_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    installment_number: Mapped[int] = mapped_column(Integer, nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount_due_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_paid_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[FundingInstallmentStatus] = mapped_column(
        Enum(FundingInstallmentStatus, name="funding_installment_status"),
        nullable=False,
    )

    funding = relationship("BusinessFunding", back_populates="installments")
    business = relationship("Business", back_populates="funding_installments")
    payment_entry = relationship("BusinessCashEntry", back_populates="funding_installment")
