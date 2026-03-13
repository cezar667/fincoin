import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin
from app.infrastructure.db.models.enums import BusinessCashActivityType, TransactionDirection


class BusinessCashEntry(Base, TimestampMixin):
    __tablename__ = "business_cash_entries"
    __table_args__ = (
        Index("ix_business_cash_entries_business_date", "business_id", "occurred_on"),
        Index("ix_business_cash_entries_account_date", "business_account_id", "occurred_on"),
        Index("ix_business_cash_entries_business_direction", "business_id", "direction"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("business_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    business_category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("business_categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    cost_center_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("cost_centers.id", ondelete="SET NULL"),
        nullable=True,
    )
    funding_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("business_fundings.id", ondelete="SET NULL"),
        nullable=True,
    )
    activity_type: Mapped[BusinessCashActivityType] = mapped_column(
        Enum(BusinessCashActivityType, name="business_cash_activity_type"),
        nullable=False,
    )
    direction: Mapped[TransactionDirection] = mapped_column(
        Enum(TransactionDirection, name="transaction_direction"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    business = relationship("Business", back_populates="cash_entries")
    account = relationship("BusinessAccount", back_populates="cash_entries")
    category = relationship("BusinessCategory", back_populates="cash_entries")
    cost_center = relationship("CostCenter", back_populates="cash_entries")
    funding = relationship("BusinessFunding", back_populates="cash_entries")
    funding_installment = relationship(
        "BusinessFundingInstallment",
        back_populates="payment_entry",
        uselist=False,
    )
