from dataclasses import dataclass
from datetime import date

from app.domain.services.traffic_light import TrafficLight, classify_balance
from app.domain.value_objects.month import Month


@dataclass(frozen=True, slots=True)
class MonthlyFlow:
    month: date
    income_cents: int
    expense_cents: int


@dataclass(frozen=True, slots=True)
class ForecastLine:
    month: date
    income_cents: int
    expense_cents: int
    net_cents: int
    cumulative_cents: int
    traffic_light: TrafficLight


def build_forecast_lines(
    *,
    start_month: date,
    months: int,
    initial_balance_cents: int,
    flows: dict[date, MonthlyFlow],
    yellow_threshold_cents: int,
) -> list[ForecastLine]:
    if months <= 0:
        return []
    base = Month.from_any_date(start_month)
    cumulative = initial_balance_cents
    out: list[ForecastLine] = []
    for idx in range(months):
        month = base.add_months(idx).value
        flow = flows.get(month, MonthlyFlow(month, 0, 0))
        net = flow.income_cents - flow.expense_cents
        cumulative += net
        out.append(
            ForecastLine(
                month=month,
                income_cents=flow.income_cents,
                expense_cents=flow.expense_cents,
                net_cents=net,
                cumulative_cents=cumulative,
                traffic_light=classify_balance(cumulative, yellow_threshold_cents),
            )
        )
    return out

