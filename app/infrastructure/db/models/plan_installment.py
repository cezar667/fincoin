import uuid

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin


class PlanInstallment(Base, TimestampMixin):
    __tablename__ = "plan_installments"
    __table_args__ = (
        Index("ix_plan_installments_plan_id", "plan_id"),
        UniqueConstraint("installment_id", name="uq_plan_installments_installment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("financial_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    installment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("installments.id", ondelete="CASCADE"),
        nullable=False,
    )
