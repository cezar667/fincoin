import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, Enum, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin
from app.infrastructure.db.models.enums import ReceivableKind, ReceivableStatus


class Receivable(Base, TimestampMixin):
    __tablename__ = "receivables"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "kind",
            "competency_month",
            name="uq_receivables_subscription_kind_competency",
        ),
        UniqueConstraint("business_id", "external_invoice_id", name="uq_receivables_business_external_invoice"),
        Index("ix_receivables_business_status_due", "business_id", "status", "due_on"),
        Index("ix_receivables_member_due", "member_id", "due_on"),
        Index("ix_receivables_business_external_order", "business_id", "external_order_id"),
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
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("subscriptions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    kind: Mapped[ReceivableKind] = mapped_column(
        Enum(ReceivableKind, name="receivable_kind"),
        nullable=False,
    )
    status: Mapped[ReceivableStatus] = mapped_column(
        Enum(ReceivableStatus, name="receivable_status"),
        nullable=False,
    )
    external_invoice_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_cents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    competency_month: Mapped[date] = mapped_column(Date, nullable=False)

    business = relationship("Business", back_populates="receivables")
    member = relationship("Member", back_populates="receivables")
    subscription = relationship("Subscription", back_populates="receivables")
    receipts = relationship("Receipt", back_populates="receivable")
