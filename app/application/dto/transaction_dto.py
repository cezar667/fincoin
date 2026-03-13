from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.value_objects.month import Month
from app.infrastructure.db.models.enums import TransactionDirection


class CreateTransactionDTO(BaseModel):
    account_id: UUID
    category_id: UUID
    description: str | None = None
    amount_cents: int = Field(gt=0)
    direction: TransactionDirection
    occurred_on: date
    competency_month: date
    is_recurring_instance: bool = False

    @field_validator("competency_month")
    @classmethod
    def normalize_month(cls, value: date) -> date:
        return Month.from_any_date(value).value


class UpdateTransactionDTO(BaseModel):
    description: str | None = None
    amount_cents: int | None = Field(default=None, gt=0)
    category_id: UUID | None = None
    occurred_on: date | None = None
    competency_month: date | None = None

    @field_validator("competency_month")
    @classmethod
    def normalize_month(cls, value: date | None) -> date | None:
        if value is None:
            return None
        return Month.from_any_date(value).value


class TransactionReadDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    category_id: UUID
    description: str | None
    amount_cents: int
    direction: TransactionDirection
    occurred_on: date
    competency_month: date
    is_recurring_instance: bool

