from datetime import date

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

