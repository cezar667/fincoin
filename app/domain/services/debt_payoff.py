from dataclasses import dataclass
from datetime import date

from app.domain.value_objects.month import Month


@dataclass(frozen=True, slots=True)
class DebtSnapshot:
    id: str
    name: str
    balance_cents: int
    minimum_payment_cents: int
    interest_apr_bps: int


@dataclass(frozen=True, slots=True)
class DebtPayoffLine:
    debt_id: str
    name: str
    payoff_month: date | None
    months: int | None
    interest_paid_cents: int


@dataclass(frozen=True, slots=True)
class DebtPayoffResult:
    strategy: str
    debt_free_month: date | None
    total_months: int | None
    total_interest_cents: int
    lines: list[DebtPayoffLine]


def simulate_debt_payoff(
    debts: list[DebtSnapshot],
    *,
    extra_monthly_cents: int,
    strategy: str,
    start_month: date,
    max_months: int = 600,
) -> DebtPayoffResult:
    active = {
        item.id: {
            "source": item,
            "balance": max(0, item.balance_cents),
            "interest": 0,
            "paid_off_at": None,
        }
        for item in debts
        if item.balance_cents > 0
    }
    if not active:
        return DebtPayoffResult(strategy, start_month, 0, 0, [])

    def priority(row: dict[str, object]) -> tuple[int, int, str]:
        source = row["source"]
        assert isinstance(source, DebtSnapshot)
        if strategy == "SNOWBALL":
            return int(row["balance"]), -source.interest_apr_bps, source.name
        return -source.interest_apr_bps, int(row["balance"]), source.name

    completed_months = 0
    monthly_debt_budget = max(0, extra_monthly_cents) + sum(
        max(0, item.minimum_payment_cents) for item in debts
    )
    for month_number in range(1, max_months + 1):
        completed_months = month_number
        open_rows = [row for row in active.values() if int(row["balance"]) > 0]
        if not open_rows:
            break

        for row in open_rows:
            source = row["source"]
            assert isinstance(source, DebtSnapshot)
            monthly_interest = round(
                int(row["balance"]) * (source.interest_apr_bps / 10_000) / 12
            )
            row["balance"] = int(row["balance"]) + monthly_interest
            row["interest"] = int(row["interest"]) + monthly_interest

        rollover = monthly_debt_budget
        for row in open_rows:
            source = row["source"]
            assert isinstance(source, DebtSnapshot)
            payment = min(int(row["balance"]), max(0, source.minimum_payment_cents))
            row["balance"] = int(row["balance"]) - payment
            rollover -= payment
            if int(row["balance"]) == 0:
                row["paid_off_at"] = month_number

        for row in sorted(active.values(), key=priority):
            if rollover <= 0:
                break
            balance = int(row["balance"])
            if balance <= 0:
                continue
            payment = min(balance, rollover)
            row["balance"] = balance - payment
            rollover -= payment
            if int(row["balance"]) == 0:
                row["paid_off_at"] = month_number

        if all(int(row["balance"]) <= 0 for row in active.values()):
            break

    paid_all = all(int(row["balance"]) <= 0 for row in active.values())
    base = Month.from_any_date(start_month)
    lines: list[DebtPayoffLine] = []
    for row in sorted(active.values(), key=priority):
        source = row["source"]
        assert isinstance(source, DebtSnapshot)
        months = row["paid_off_at"] if isinstance(row["paid_off_at"], int) else None
        lines.append(
            DebtPayoffLine(
                debt_id=source.id,
                name=source.name,
                payoff_month=base.add_months(months - 1).value if months else None,
                months=months,
                interest_paid_cents=int(row["interest"]),
            )
        )
    return DebtPayoffResult(
        strategy=strategy,
        debt_free_month=base.add_months(completed_months - 1).value
        if paid_all
        else None,
        total_months=completed_months if paid_all else None,
        total_interest_cents=sum(line.interest_paid_cents for line in lines),
        lines=lines,
    )
