import uuid

from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.infrastructure.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    businesses = relationship(
        "Business",
        back_populates="owner",
        cascade="all, delete-orphan",
        foreign_keys="Business.owner_user_id",
    )
    business_audit_logs = relationship(
        "AuditLog",
        back_populates="actor_user",
        foreign_keys="AuditLog.actor_user_id",
    )
    categories = relationship("Category", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    import_files = relationship("ImportFile", back_populates="user", cascade="all, delete-orphan")
    external_transactions = relationship(
        "ExternalTransaction",
        back_populates="user",
        cascade="all, delete-orphan",
    )
