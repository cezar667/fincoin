import uuid

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin
from app.infrastructure.db.models.enums import BusinessAccountType


class BusinessAccount(Base, TimestampMixin):
    __tablename__ = "business_accounts"
    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_business_accounts_business_name"),
        Index("ix_business_accounts_business_active", "business_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    type: Mapped[BusinessAccountType] = mapped_column(
        Enum(BusinessAccountType, name="business_account_type"),
        nullable=False,
    )
    institution_name: Mapped[str | None] = mapped_column(String(140), nullable=True)
    initial_balance_cents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    business = relationship("Business", back_populates="accounts")
    cash_entries = relationship("BusinessCashEntry", back_populates="account")
    disbursed_fundings = relationship(
        "BusinessFunding",
        foreign_keys="BusinessFunding.disbursement_account_id",
        back_populates="disbursement_account",
    )
    settled_fundings = relationship(
        "BusinessFunding",
        foreign_keys="BusinessFunding.settlement_account_id",
        back_populates="settlement_account",
    )
