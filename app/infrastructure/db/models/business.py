import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin


class Business(Base, TimestampMixin):
    __tablename__ = "businesses"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_businesses_slug"),
        Index("ix_businesses_owner_active", "owner_user_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL", server_default="BRL")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    owner = relationship("User", back_populates="businesses")
    accounts = relationship("BusinessAccount", back_populates="business", cascade="all, delete-orphan")
    categories = relationship("BusinessCategory", back_populates="business", cascade="all, delete-orphan")
    cost_centers = relationship("CostCenter", back_populates="business", cascade="all, delete-orphan")
    cash_entries = relationship("BusinessCashEntry", back_populates="business", cascade="all, delete-orphan")
    fundings = relationship("BusinessFunding", back_populates="business", cascade="all, delete-orphan")
    funding_installments = relationship(
        "BusinessFundingInstallment",
        back_populates="business",
        cascade="all, delete-orphan",
    )
    integrations = relationship("BusinessIntegration", back_populates="business", cascade="all, delete-orphan")
    members = relationship("Member", back_populates="business", cascade="all, delete-orphan")
    membership_plans = relationship("MembershipPlan", back_populates="business", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="business", cascade="all, delete-orphan")
    receivables = relationship("Receivable", back_populates="business", cascade="all, delete-orphan")
    receipts = relationship("Receipt", back_populates="business", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="business", cascade="all, delete-orphan")
    webhook_events = relationship("WebhookEvent", back_populates="business", cascade="all, delete-orphan")
