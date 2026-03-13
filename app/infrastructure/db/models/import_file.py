import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, utc_now
from app.infrastructure.db.models.enums import ImportFileStatus


class ImportFile(Base):
    __tablename__ = "import_files"
    __table_args__ = (Index("ix_import_files_user_uploaded_at", "user_id", "uploaded_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    status: Mapped[ImportFileStatus] = mapped_column(
        Enum(ImportFileStatus, name="import_file_status"),
        nullable=False,
        default=ImportFileStatus.IMPORTED,
        server_default=ImportFileStatus.IMPORTED.value,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("User", back_populates="import_files")
    external_transactions = relationship(
        "ExternalTransaction",
        back_populates="import_file",
        cascade="all, delete-orphan",
    )
