import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin


class BusinessFunding(Base, TimestampMixin):
    __tablename__ = "business_fundings"
    __table_args__ = (
        Index("ix_business_fundings_business_disbursed", "business_id", "disbursed_on"),
        Index("ix_business_fundings_business_first_due", "business_id", "first_due_on"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
    )
    disbursement_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("business_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    settlement_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("business_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payment_category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("business_categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    cost_center_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("cost_centers.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    lender_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    principal_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    installment_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    installment_count: Mapped[int] = mapped_column(Integer, nullable=False)
    annual_interest_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disbursed_on: Mapped[date] = mapped_column(Date, nullable=False)
    first_due_on: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    business = relationship("Business", back_populates="fundings")
    disbursement_account = relationship(
        "BusinessAccount",
        foreign_keys=[disbursement_account_id],
        back_populates="disbursed_fundings",
    )
    settlement_account = relationship(
        "BusinessAccount",
        foreign_keys=[settlement_account_id],
        back_populates="settled_fundings",
    )
    payment_category = relationship("BusinessCategory", back_populates="fundings")
    cost_center = relationship("CostCenter", back_populates="fundings")
    installments = relationship(
        "BusinessFundingInstallment",
        back_populates="funding",
        cascade="all, delete-orphan",
    )
    cash_entries = relationship("BusinessCashEntry", back_populates="funding")
