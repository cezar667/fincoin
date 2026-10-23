import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin


class MileageMovement(Base, TimestampMixin):
    __tablename__ = "mileage_movements"
    __table_args__ = (
        Index("ix_mileage_movements_program_date", "program_id", "occurred_on"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("mileage_programs.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    miles: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
