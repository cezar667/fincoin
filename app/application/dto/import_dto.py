from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.infrastructure.db.models.enums import ExternalTransactionReviewStatus, TransactionDirection


class CSVColumnMappingDTO(BaseModel):
    date: str = "date"
    description: str = "description"
    amount: str = "amount"
    external_id: str | None = "external_id"
    type: str | None = "type"


class ExternalTransactionCreateDTO(BaseModel):
    user_id: UUID
    import_file_id: UUID
    source: str = "csv"
    card_id: UUID | None = None
    raw_date: date
    raw_description: str
    raw_amount_cents: int
    normalized_date: date
    normalized_description: str
    amount_cents: int
    direction: TransactionDirection
    external_id: str | None = None
    hash: str = Field(min_length=64, max_length=64)
    raw_row_json: dict[str, Any]
    review_status: ExternalTransactionReviewStatus = ExternalTransactionReviewStatus.PENDING
    mapped_category_id: UUID | None = None
    mapped_account_id: UUID | None = None

    @field_validator("raw_description", "normalized_description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Description cannot be empty")
        return trimmed


class CSVImportLineErrorDTO(BaseModel):
    line_number: int
    message: str
    row_data: dict[str, Any]


class CSVImportParseResultDTO(BaseModel):
    total_linhas: int = 0
    importadas: int = 0
    duplicadas: int = 0
    com_erro: int = 0
    items: list[ExternalTransactionCreateDTO] = Field(default_factory=list)
    errors: list[CSVImportLineErrorDTO] = Field(default_factory=list)


class ImportCSVSummaryDTO(BaseModel):
    import_file_id: UUID
    total_linhas: int
    importadas: int
    duplicadas: int
    com_erro: int
    errors: list[CSVImportLineErrorDTO] = Field(default_factory=list)


class ExternalTransactionReadDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    import_file_id: UUID
    normalized_date: date
    normalized_description: str
    amount_cents: int
    direction: TransactionDirection
    review_status: ExternalTransactionReviewStatus
    mapped_category_id: UUID | None
    mapped_account_id: UUID | None


class ApplyImportPayloadDTO(BaseModel):
    default_account_id: UUID
    default_category_id: UUID | None = None
    approve_all: bool = True
    approved_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_approved_ids(self) -> "ApplyImportPayloadDTO":
        if not self.approve_all and not self.approved_ids:
            raise ValueError("approved_ids is required when approve_all is false")
        return self


class ApplyImportResultDTO(BaseModel):
    applied_count: int
    skipped_count: int
    errors: list[str] = Field(default_factory=list)
