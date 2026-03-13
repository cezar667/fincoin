import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin
from app.infrastructure.db.models.enums import BusinessCategoryKind


class BusinessCategory(Base, TimestampMixin):
    __tablename__ = "business_categories"
    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_business_categories_business_name"),
        Index("ix_business_categories_business_kind", "business_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    kind: Mapped[BusinessCategoryKind] = mapped_column(
        Enum(BusinessCategoryKind, name="business_category_kind"),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    business = relationship("Business", back_populates="categories")
    cash_entries = relationship("BusinessCashEntry", back_populates="category")
    fundings = relationship("BusinessFunding", back_populates="payment_category")
