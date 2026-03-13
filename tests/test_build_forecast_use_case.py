from datetime import date
from uuid import UUID, uuid4

from app.application.use_cases.build_forecast import BuildForecastUseCase
from app.domain.services.forecast_engine import MonthlyFlow


class StubForecastRepository:
    def __init__(self, *, initial_balance_cents: int) -> None:
        self.initial_balance_cents = initial_balance_cents
        self.sum_initial_balance_calls = 0

    def sum_account_initial_balances(self, user_id: UUID) -> int:
        self.sum_initial_balance_calls += 1
        return self.initial_balance_cents

    def build_flow_map(
        self,
        user_id: UUID,
        from_month: date,
        months: int,
        plan_id: UUID | None = None,
    ) -> dict[date, MonthlyFlow]:
        del user_id, months, plan_id
        return {
            from_month: MonthlyFlow(
                month=from_month,
                income_cents=200_00,
                expense_cents=50_00,
            )
        }


def test_build_forecast_uses_sum_of_account_initial_balances_by_default() -> None:
    repo = StubForecastRepository(initial_balance_cents=-400_00)
    result = BuildForecastUseCase(repo).execute(
        user_id=uuid4(),
        from_month=date(2026, 3, 1),
        months=1,
    )
    assert repo.sum_initial_balance_calls == 1
    assert result.initial_balance_cents == -400_00
    assert result.lines[0].cumulative_cents == -250_00


def test_build_forecast_accepts_explicit_initial_balance_override() -> None:
    repo = StubForecastRepository(initial_balance_cents=999_99)
    result = BuildForecastUseCase(repo).execute(
        user_id=uuid4(),
        from_month=date(2026, 3, 1),
        months=1,
        initial_balance_cents=100_00,
    )
    assert repo.sum_initial_balance_calls == 0
    assert result.initial_balance_cents == 100_00
    assert result.lines[0].cumulative_cents == 250_00
