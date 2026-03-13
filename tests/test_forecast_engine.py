from datetime import date

from app.domain.services.forecast_engine import MonthlyFlow, build_forecast_lines


def test_forecast_engine_builds_cumulative() -> None:
    flows = {
        date(2026, 2, 1): MonthlyFlow(month=date(2026, 2, 1), income_cents=500_00, expense_cents=200_00),
        date(2026, 3, 1): MonthlyFlow(month=date(2026, 3, 1), income_cents=300_00, expense_cents=450_00),
    }
    lines = build_forecast_lines(
        start_month=date(2026, 2, 1),
        months=3,
        initial_balance_cents=100_00,
        flows=flows,
        yellow_threshold_cents=100_00,
    )
    assert len(lines) == 3
    assert lines[0].cumulative_cents == 400_00
    assert lines[1].cumulative_cents == 250_00

