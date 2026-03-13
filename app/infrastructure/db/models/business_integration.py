import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin
from app.infrastructure.db.models.enums import IntegrationProvider


class BusinessIntegration(Base, TimestampMixin):
    __tablename__ = "business_integrations"
    __table_args__ = (
        UniqueConstraint("business_id", "provider", name="uq_business_integrations_business_provider"),
        UniqueConstraint("webhook_path_token", name="uq_business_integrations_webhook_path_token"),
        Index("ix_business_integrations_business_active", "business_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[IntegrationProvider] = mapped_column(
        Enum(IntegrationProvider, name="integration_provider"),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    webhook_path_token: Mapped[str] = mapped_column(String(80), nullable=False)
    webhook_secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    webhook_secret_hint: Mapped[str] = mapped_column(String(12), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)

    business = relationship("Business", back_populates="integrations")
    webhook_events = relationship("WebhookEvent", back_populates="integration", cascade="all, delete-orphan")
