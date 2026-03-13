import uuid

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin
from app.infrastructure.db.models.enums import BillingCadence


class MembershipPlan(Base, TimestampMixin):
    __tablename__ = "membership_plans"
    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_membership_plans_business_name"),
        UniqueConstraint("business_id", "external_product_id", name="uq_membership_plans_business_external_product"),
        UniqueConstraint("business_id", "external_reference_id", name="uq_membership_plans_business_external_reference"),
        Index("ix_membership_plans_business_active", "business_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_product_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_reference_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cadence: Mapped[BillingCadence] = mapped_column(Enum(BillingCadence, name="billing_cadence"), nullable=False)
    recurring_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activation_fee_cents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    billing_day: Mapped[int] = mapped_column(Integer, nullable=False)
    grace_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    business = relationship("Business", back_populates="membership_plans")
    subscriptions = relationship("Subscription", back_populates="membership_plan")
