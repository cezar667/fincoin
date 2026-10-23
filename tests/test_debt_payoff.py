from datetime import date

from app.domain.services.debt_payoff import DebtSnapshot, simulate_debt_payoff


def test_avalanche_prioritizes_highest_interest_and_finishes() -> None:
    debts = [
        DebtSnapshot("cheap", "Financiamento", 10_000_00, 500_00, 600),
        DebtSnapshot("expensive", "Cartão", 3_000_00, 300_00, 3_600),
    ]

    result = simulate_debt_payoff(
        debts,
        extra_monthly_cents=500_00,
        strategy="AVALANCHE",
        start_month=date(2026, 10, 1),
    )

    assert result.debt_free_month is not None
    assert result.total_months is not None
    expensive = next(line for line in result.lines if line.debt_id == "expensive")
    cheap = next(line for line in result.lines if line.debt_id == "cheap")
    assert expensive.months < cheap.months


def test_paid_minimum_rolls_into_next_debt() -> None:
    debts = [
        DebtSnapshot("one", "Dívida pequena", 100_00, 100_00, 0),
        DebtSnapshot("two", "Dívida maior", 300_00, 100_00, 0),
    ]

    result = simulate_debt_payoff(
        debts,
        extra_monthly_cents=0,
        strategy="SNOWBALL",
        start_month=date(2026, 10, 1),
    )

    assert result.total_months == 2
    assert result.debt_free_month == date(2026, 11, 1)
