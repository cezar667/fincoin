import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin


class MileageProgram(Base, TimestampMixin):
    __tablename__ = "mileage_programs"
    __table_args__ = (
        Index("ix_mileage_programs_user_expiry", "user_id", "expires_on"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    balance_miles: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    target_miles: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
