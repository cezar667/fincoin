from datetime import date
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infrastructure.db import models as _models  # noqa: F401
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.account import Account
from app.infrastructure.db.models.category import Category
from app.infrastructure.db.models.credit_card import CreditCard
from app.infrastructure.db.models.debt import Debt
from app.infrastructure.db.models.debt_plan import DebtPlan
from app.infrastructure.db.models.enums import (
    AccountType,
    CategoryKind,
    DebtKind,
    InstallmentKind,
    RecurringCadence,
    TransactionDirection,
)
from app.infrastructure.db.models.financial_plan import FinancialPlan
from app.infrastructure.db.models.installment import Installment
from app.infrastructure.db.models.plan_installment import PlanInstallment
from app.infrastructure.db.models.plan_recurring_rule import PlanRecurringRule
from app.infrastructure.db.models.plan_transaction import PlanTransaction
from app.infrastructure.db.models.recurring_rule import RecurringRule
from app.infrastructure.db.models.transaction import Transaction
from app.infrastructure.db.models.user import User
from app.infrastructure.repositories.transaction_repo import (
    SQLAlchemyForecastRepository,
)


def test_month_details_explain_forecast_and_sort_expenses() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        user = User(
            id=uuid4(), email="forecast-details@test.local", password_hash="hash"
        )
        account = Account(
            id=uuid4(), user_id=user.id, name="Conta", type=AccountType.BANK
        )
        category = Category(
            id=uuid4(), user_id=user.id, name="Casa", kind=CategoryKind.EXPENSE
        )
        food_category = Category(
            id=uuid4(),
            user_id=user.id,
            name="Alimentação",
            kind=CategoryKind.EXPENSE,
        )
        income_category = Category(
            id=uuid4(), user_id=user.id, name="Salário", kind=CategoryKind.INCOME
        )
        card = CreditCard(
            id=uuid4(), user_id=user.id, name="Cartão", closing_day=5, due_day=12
        )
        plan = FinancialPlan(id=uuid4(), user_id=user.id, name="Plano familiar")
        transaction = Transaction(
            id=uuid4(),
            user_id=user.id,
            account_id=account.id,
            category_id=category.id,
            description="Conta avulsa",
            amount_cents=100_00,
            direction=TransactionDirection.EXPENSE,
            occurred_on=date(2026, 10, 4),
            competency_month=date(2026, 10, 1),
        )
        food_transaction = Transaction(
            id=uuid4(),
            user_id=user.id,
            account_id=account.id,
            category_id=food_category.id,
            description="Mercado",
            amount_cents=50_00,
            direction=TransactionDirection.EXPENSE,
            occurred_on=date(2026, 10, 5),
            competency_month=date(2026, 10, 1),
        )
        income_transaction = Transaction(
            id=uuid4(),
            user_id=user.id,
            account_id=account.id,
            category_id=income_category.id,
            description="Bônus",
            amount_cents=500_00,
            direction=TransactionDirection.INCOME,
            occurred_on=date(2026, 10, 2),
            competency_month=date(2026, 10, 1),
        )
        recurring = RecurringRule(
            id=uuid4(),
            user_id=user.id,
            name="Condomínio",
            amount_cents=200_00,
            direction=TransactionDirection.EXPENSE,
            category_id=category.id,
            account_id=account.id,
            cadence=RecurringCadence.MONTHLY,
            day_of_month=10,
            start_month=date(2026, 10, 1),
            end_month=None,
        )
        income_recurring = RecurringRule(
            id=uuid4(),
            user_id=user.id,
            name="Salário mensal",
            amount_cents=5_000_00,
            direction=TransactionDirection.INCOME,
            category_id=income_category.id,
            account_id=account.id,
            cadence=RecurringCadence.MONTHLY,
            day_of_month=5,
            start_month=date(2026, 10, 1),
            end_month=None,
        )
        installment = Installment(
            id=uuid4(),
            user_id=user.id,
            credit_card_id=card.id,
            category_id=category.id,
            description="Geladeira",
            total_parts=2,
            part_amount_cents=300_00,
            first_competency_month=date(2026, 10, 1),
        )
        financing = Installment(
            id=uuid4(),
            user_id=user.id,
            credit_card_id=None,
            category_id=category.id,
            kind=InstallmentKind.FINANCING,
            description="Financiamento do carro",
            creditor="Banco",
            financed_amount_cents=20_000_00,
            interest_apr_bps=1_200,
            due_day=15,
            total_parts=2,
            part_amount_cents=600_00,
            first_competency_month=date(2026, 10, 1),
        )
        debt = Debt(
            id=uuid4(),
            user_id=user.id,
            name="Empréstimo",
            kind=DebtKind.LOAN,
            principal_cents=4_000_00,
            current_balance_cents=4_000_00,
            minimum_payment_cents=400_00,
            interest_apr_bps=1200,
            start_month=date(2026, 10, 1),
            creditor="Banco",
        )
        debt_plan = DebtPlan(
            id=uuid4(),
            debt_id=debt.id,
            user_id=user.id,
            monthly_payment_cents=400_00,
            start_month=date(2026, 10, 1),
            end_month=None,
        )
        db.add_all(
            [
                user,
                account,
                category,
                food_category,
                income_category,
                card,
                plan,
                transaction,
                food_transaction,
                income_transaction,
                recurring,
                income_recurring,
                installment,
                financing,
                debt,
                debt_plan,
                PlanTransaction(plan_id=plan.id, transaction_id=transaction.id),
                PlanTransaction(plan_id=plan.id, transaction_id=food_transaction.id),
                PlanTransaction(plan_id=plan.id, transaction_id=income_transaction.id),
                PlanRecurringRule(plan_id=plan.id, recurring_rule_id=recurring.id),
                PlanRecurringRule(
                    plan_id=plan.id, recurring_rule_id=income_recurring.id
                ),
                PlanInstallment(plan_id=plan.id, installment_id=installment.id),
                PlanInstallment(plan_id=plan.id, installment_id=financing.id),
            ]
        )
        db.commit()

        repository = SQLAlchemyForecastRepository(db)
        flows = repository.build_flow_map(
            user_id=user.id,
            from_month=date(2026, 10, 1),
            months=2,
            plan_id=plan.id,
        )
        details = repository.build_expense_details(
            user_id=user.id,
            from_month=date(2026, 10, 1),
            months=2,
            plan_id=plan.id,
        )
        income_details = repository.build_income_details(
            user_id=user.id,
            from_month=date(2026, 10, 1),
            months=2,
            plan_id=plan.id,
        )

        assert {item.source_type for item in details[date(2026, 10, 1)]} == {
            "TRANSACTION",
            "RECURRING_EXPENSE",
            "INSTALLMENT",
            "FINANCING",
            "DEBT",
        }
        october_expenses = details[date(2026, 10, 1)]
        assert [item.source_type for item in october_expenses] == [
            "TRANSACTION",
            "TRANSACTION",
            "RECURRING_EXPENSE",
            "INSTALLMENT",
            "FINANCING",
            "DEBT",
        ]
        assert [item.category_name for item in october_expenses[:2]] == [
            "Alimentação",
            "Casa",
        ]
        assert [item.source_type for item in income_details[date(2026, 10, 1)]] == [
            "TRANSACTION",
            "RECURRING_INCOME",
        ]
        recurring_income_detail = income_details[date(2026, 10, 1)][1]
        assert recurring_income_detail.source_label == "Receita recorrente"
        financing_detail = next(
            item for item in october_expenses if item.source_type == "FINANCING"
        )
        assert financing_detail.source_label == "Financiamento"
        assert financing_detail.detail == "Parcela 1/2 · Banco"
        for month in (date(2026, 10, 1), date(2026, 11, 1)):
            assert (
                sum(item.amount_cents for item in details[month])
                == flows[month].expense_cents
            )
            assert (
                sum(item.amount_cents for item in income_details[month])
                == flows[month].income_cents
            )
