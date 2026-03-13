from datetime import date
from uuid import UUID

from app.application.dto.forecast_dto import ForecastDTO, ForecastMonthDTO
from app.application.ports.repositories import ForecastRepositoryPort
from app.domain.services.forecast_engine import build_forecast_lines
from app.domain.value_objects.month import Month


class BuildForecastUseCase:
    def __init__(self, repo: ForecastRepositoryPort) -> None:
        self.repo = repo

    def execute(
        self,
        *,
        user_id: UUID,
        from_month: date,
        months: int = 6,
        plan_id: UUID | None = None,
        initial_balance_cents: int | None = None,
        yellow_threshold_cents: int = 100_000,
    ) -> ForecastDTO:
        normalized = Month.from_any_date(from_month).value
        effective_initial_balance_cents = (
            initial_balance_cents
            if initial_balance_cents is not None
            else self.repo.sum_account_initial_balances(user_id)
        )
        flows = self.repo.build_flow_map(
            user_id=user_id,
            from_month=normalized,
            months=months,
            plan_id=plan_id,
        )
        lines = build_forecast_lines(
            start_month=normalized,
            months=months,
            initial_balance_cents=effective_initial_balance_cents,
            flows=flows,
            yellow_threshold_cents=yellow_threshold_cents,
        )
        return ForecastDTO(
            from_month=normalized,
            months=months,
            initial_balance_cents=effective_initial_balance_cents,
            lines=[
                ForecastMonthDTO(
                    month=item.month,
                    income_cents=item.income_cents,
                    expense_cents=item.expense_cents,
                    net_cents=item.net_cents,
                    cumulative_cents=item.cumulative_cents,
                    traffic_light=item.traffic_light.value,
                )
                for item in lines
            ],
        )
