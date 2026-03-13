import re
from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.infrastructure.db.models.enums import (
    BillingCadence,
    BusinessAccountType,
    BusinessCashActivityType,
    BusinessCategoryKind,
    FundingInstallmentStatus,
    MemberStatus,
    ReceiptMethod,
    TransactionDirection,
)


def _normalize_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Campo obrigatorio.")
    return normalized


def _slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    if not text:
        raise ValueError("Slug invalido.")
    return text


def _normalize_code(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if not normalized:
        return None
    normalized = re.sub(r"[^A-Z0-9_-]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or None


class CreateBusinessDTO(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=80)
    legal_name: str | None = Field(default=None, max_length=180)
    description: str | None = Field(default=None, max_length=500)
    seed_template: str | None = Field(default=None, max_length=40)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _normalize_text(value)

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return _slugify(value)

    @field_validator("legal_name", "description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("seed_template")
    @classmethod
    def normalize_seed_template(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None


class UpsertBusinessAccountDTO(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    type: BusinessAccountType
    institution_name: str | None = Field(default=None, max_length=140)
    initial_balance_cents: int = 0

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _normalize_text(value)

    @field_validator("institution_name")
    @classmethod
    def normalize_institution_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class UpsertBusinessCategoryDTO(BaseModel):
    code: str | None = Field(default=None, max_length=40)
    name: str = Field(min_length=2, max_length=140)
    kind: BusinessCategoryKind
    description: str | None = Field(default=None, max_length=255)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        return _normalize_code(value)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _normalize_text(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class UpsertCostCenterDTO(BaseModel):
    code: str | None = Field(default=None, max_length=40)
    name: str = Field(min_length=2, max_length=140)
    description: str | None = Field(default=None, max_length=255)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        return _normalize_code(value)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _normalize_text(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class BusinessReadDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    legal_name: str | None
    description: str | None
    currency_code: str
    is_active: bool


class CreateMemberDTO(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    document_number: str | None = Field(default=None, max_length=40)
    status: MemberStatus = MemberStatus.ACTIVE
    joined_on: date
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        return _normalize_text(value)

    @field_validator("email", "phone", "document_number", "notes")
    @classmethod
    def normalize_optional_member_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class UpsertMembershipPlanDTO(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    description: str | None = Field(default=None, max_length=255)
    external_product_id: str | None = Field(default=None, max_length=120)
    external_reference_id: str | None = Field(default=None, max_length=120)
    cadence: BillingCadence = BillingCadence.MONTHLY
    recurring_amount_cents: int = Field(gt=0)
    activation_fee_cents: int = Field(default=0, ge=0)
    billing_day: int = Field(ge=1, le=28)
    grace_days: int = Field(default=0, ge=0, le=90)

    @field_validator("name")
    @classmethod
    def normalize_plan_name(cls, value: str) -> str:
        return _normalize_text(value)

    @field_validator("description", "external_product_id", "external_reference_id")
    @classmethod
    def normalize_plan_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CreateSubscriptionDTO(BaseModel):
    member_id: UUID
    membership_plan_id: UUID
    started_on: date
    first_due_on: date
    price_override_cents: int | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("notes")
    @classmethod
    def normalize_subscription_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class RecordReceiptDTO(BaseModel):
    received_on: date
    amount_received_cents: int = Field(gt=0)
    method: ReceiptMethod
    note: str | None = Field(default=None, max_length=255)

    @field_validator("note")
    @classmethod
    def normalize_receipt_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CreateBusinessCashEntryDTO(BaseModel):
    business_account_id: UUID
    business_category_id: UUID | None = None
    cost_center_id: UUID | None = None
    funding_id: UUID | None = None
    activity_type: BusinessCashActivityType = BusinessCashActivityType.OPERATING
    direction: TransactionDirection
    description: str = Field(min_length=2, max_length=255)
    amount_cents: int = Field(gt=0)
    occurred_on: date
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("description")
    @classmethod
    def normalize_cash_entry_description(cls, value: str) -> str:
        return _normalize_text(value)

    @field_validator("notes")
    @classmethod
    def normalize_cash_entry_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CreateBusinessFundingDTO(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    lender_name: str | None = Field(default=None, max_length=160)
    disbursement_account_id: UUID
    settlement_account_id: UUID
    payment_category_id: UUID | None = None
    cost_center_id: UUID | None = None
    principal_cents: int = Field(gt=0)
    installment_amount_cents: int = Field(gt=0)
    installment_count: int = Field(gt=0, le=360)
    annual_interest_bps: int | None = Field(default=None, ge=0, le=100_000)
    disbursed_on: date
    first_due_on: date
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_funding_name(cls, value: str) -> str:
        return _normalize_text(value)

    @field_validator("lender_name", "notes")
    @classmethod
    def normalize_funding_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PayBusinessFundingInstallmentDTO(BaseModel):
    paid_on: date
    amount_paid_cents: int = Field(gt=0)
    notes: str | None = Field(default=None, max_length=255)
    status: FundingInstallmentStatus = FundingInstallmentStatus.PAID

    @field_validator("status")
    @classmethod
    def validate_paid_status(cls, value: FundingInstallmentStatus) -> FundingInstallmentStatus:
        if value != FundingInstallmentStatus.PAID:
            raise ValueError("A baixa manual so aceita o status PAID.")
        return value

    @field_validator("notes")
    @classmethod
    def normalize_installment_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
