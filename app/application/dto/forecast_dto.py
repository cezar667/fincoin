from datetime import date
from uuid import UUID

from pydantic import BaseModel


class ForecastMonthDTO(BaseModel):
    month: date
    income_cents: int
    expense_cents: int
    net_cents: int
    cumulative_cents: int
    traffic_light: str


class ForecastDTO(BaseModel):
    from_month: date
    months: int
    initial_balance_cents: int
    lines: list[ForecastMonthDTO]


class ForecastFlowItemDTO(BaseModel):
    month: date
    source_id: UUID
    source_type: str
    source_label: str
    description: str
    category_name: str | None = None
    detail: str | None = None
    amount_cents: int
    edit_url: str
