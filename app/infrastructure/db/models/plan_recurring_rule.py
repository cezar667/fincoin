import uuid

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin


class PlanRecurringRule(Base, TimestampMixin):
    __tablename__ = "plan_recurring_rules"
    __table_args__ = (
        Index("ix_plan_recurring_rules_plan_id", "plan_id"),
        UniqueConstraint("recurring_rule_id", name="uq_plan_recurring_rules_recurring_rule_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("financial_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    recurring_rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("recurring_rules.id", ondelete="CASCADE"),
        nullable=False,
    )
