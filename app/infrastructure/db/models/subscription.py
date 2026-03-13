import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin
from app.infrastructure.db.models.enums import SubscriptionStatus


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ix_subscriptions_business_status", "business_id", "status"),
        Index("ix_subscriptions_member_status", "member_id", "status"),
        Index("ix_subscriptions_business_next_billing", "business_id", "next_billing_on"),
        UniqueConstraint("business_id", "external_subscription_id", name="uq_subscriptions_business_external_subscription"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("members.id", ondelete="RESTRICT"),
        nullable=False,
    )
    membership_plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("membership_plans.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status"),
        nullable=False,
    )
    started_on: Mapped[date] = mapped_column(Date, nullable=False)
    next_billing_on: Mapped[date] = mapped_column(Date, nullable=False)
    external_subscription_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    price_override_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    business = relationship("Business", back_populates="subscriptions")
    member = relationship("Member", back_populates="subscriptions")
    membership_plan = relationship("MembershipPlan", back_populates="subscriptions")
    receivables = relationship("Receivable", back_populates="subscription")
