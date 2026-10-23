import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin


class CategoryBudget(Base, TimestampMixin):
    __tablename__ = "category_budgets"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "category_id", name="uq_category_budgets_user_category"
        ),
        Index("ix_category_budgets_user_active", "user_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    monthly_limit_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    alert_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=80, server_default=text("80")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
