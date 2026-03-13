import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from app.infrastructure.db.base import Base, utc_now
from app.infrastructure.db.models.enums import ExternalTransactionReviewStatus, TransactionDirection

RAW_ROW_JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class ExternalTransaction(Base):
    __tablename__ = "external_transactions"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "hash", name="uq_external_transactions_user_source_hash"),
        Index("ix_external_transactions_user_import_review", "user_id", "import_file_id", "review_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    import_file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("import_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    card_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("credit_cards.id", ondelete="SET NULL"),
        nullable=True,
    )
    raw_date: Mapped[date] = mapped_column(Date, nullable=False)
    raw_description: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    normalized_date: Mapped[date] = mapped_column(Date, nullable=False)
    normalized_description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    direction: Mapped[TransactionDirection] = mapped_column(
        Enum(TransactionDirection, name="transaction_direction"),
        nullable=False,
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_row_json: Mapped[dict[str, Any]] = mapped_column(RAW_ROW_JSON_TYPE, nullable=False)
    review_status: Mapped[ExternalTransactionReviewStatus] = mapped_column(
        Enum(ExternalTransactionReviewStatus, name="external_transaction_review_status"),
        nullable=False,
        default=ExternalTransactionReviewStatus.PENDING,
        server_default=ExternalTransactionReviewStatus.PENDING.value,
    )
    mapped_category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    mapped_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )

    user = relationship("User", back_populates="external_transactions")
    import_file = relationship("ImportFile", back_populates="external_transactions")
