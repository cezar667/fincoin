import uuid
from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin
from app.infrastructure.db.models.enums import MemberStatus


class Member(Base, TimestampMixin):
    __tablename__ = "members"
    __table_args__ = (
        Index("ix_members_business_status", "business_id", "status"),
        Index("ix_members_business_joined", "business_id", "joined_on"),
        UniqueConstraint("business_id", "external_customer_id", name="uq_members_business_external_customer"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    external_customer_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    document_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[MemberStatus] = mapped_column(Enum(MemberStatus, name="member_status"), nullable=False)
    joined_on: Mapped[date] = mapped_column(Date, nullable=False)
    activated_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    business = relationship("Business", back_populates="members")
    subscriptions = relationship("Subscription", back_populates="member")
    receivables = relationship("Receivable", back_populates="member")
