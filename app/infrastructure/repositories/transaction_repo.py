from datetime import date
from typing import ClassVar
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.application.dto.forecast_dto import ForecastFlowItemDTO
from app.application.dto.transaction_dto import (
    CreateTransactionDTO,
    UpdateTransactionDTO,
)
from app.domain.services.forecast_engine import MonthlyFlow
from app.domain.value_objects.month import Month
from app.infrastructure.db.models.account import Account
from app.infrastructure.db.models.category import Category
from app.infrastructure.db.models.debt import Debt
from app.infrastructure.db.models.debt_plan import DebtPlan
from app.infrastructure.db.models.enums import TransactionDirection
from app.infrastructure.db.models.installment import Installment
from app.infrastructure.db.models.plan_installment import PlanInstallment
from app.infrastructure.db.models.plan_recurring_rule import PlanRecurringRule
from app.infrastructure.db.models.plan_transaction import PlanTransaction
from app.infrastructure.db.models.recurring_rule import RecurringRule
from app.infrastructure.db.models.transaction import Transaction


class SQLAlchemyTransactionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, user_id: UUID, payload: CreateTransactionDTO) -> Transaction:
        row = Transaction(
            user_id=user_id,
            account_id=payload.account_id,
            category_id=payload.category_id,
            description=payload.description,
            amount_cents=payload.amount_cents,
            direction=payload.direction,
            occurred_on=payload.occurred_on,
            competency_month=payload.competency_month,
            is_recurring_instance=payload.is_recurring_instance,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update(
        self, user_id: UUID, transaction_id: UUID, payload: UpdateTransactionDTO
    ) -> Transaction:
        row = self.db.get(Transaction, transaction_id)
        if row is None or row.user_id != user_id:
            raise ValueError("Transaction not found")
        for key, value in payload.model_dump(exclude_none=True).items():
            setattr(row, key, value)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, user_id: UUID, transaction_id: UUID) -> None:
        row = self.db.get(Transaction, transaction_id)
        if row is None or row.user_id != user_id:
            raise ValueError("Transaction not found")
        self.db.delete(row)
        self.db.commit()

    def list_by_month(
        self, user_id: UUID, month: date, plan_id: UUID | None = None
    ) -> list[Transaction]:
        normalized = Month.from_any_date(month).value
        stmt = (
            select(Transaction)
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.competency_month == normalized,
                )
            )
            .order_by(Transaction.occurred_on.desc(), Transaction.created_at.desc())
        )
        if plan_id is not None:
            stmt = stmt.join(
                PlanTransaction,
                PlanTransaction.transaction_id == Transaction.id,
            ).where(PlanTransaction.plan_id == plan_id)
        return list(self.db.scalars(stmt))


class SQLAlchemyForecastRepository:
    _SOURCE_ORDER: ClassVar[dict[str, int]] = {
        "TRANSACTION": 0,
        "RECURRING": 1,
        "INSTALLMENT": 2,
        "DEBT": 3,
    }

    def __init__(self, db: Session) -> None:
        self.db = db

    def sum_account_initial_balances(self, user_id: UUID) -> int:
        total = self.db.scalar(
            select(func.coalesce(func.sum(Account.initial_balance_cents), 0)).where(
                Account.user_id == user_id
            )
        )
        if total is None:
            return 0
        return int(total)

    def build_flow_map(
        self,
        user_id: UUID,
        from_month: date,
        months: int,
        plan_id: UUID | None = None,
    ) -> dict[date, MonthlyFlow]:
        month_list = [
            Month.from_any_date(from_month).add_months(i).value for i in range(months)
        ]
        flow_map = {
            m: MonthlyFlow(month=m, income_cents=0, expense_cents=0) for m in month_list
        }
        if not month_list:
            return flow_map

        self._aggregate_transactions(user_id, month_list, flow_map, plan_id=plan_id)
        self._aggregate_recurring(user_id, month_list, flow_map, plan_id=plan_id)
        self._aggregate_installments(user_id, month_list, flow_map, plan_id=plan_id)
        # Debt commitments affect every scenario until debt plans become
        # explicitly attachable to a FinancialPlan.
        self._aggregate_debt_plans(user_id, month_list, flow_map)
        return flow_map

    def build_expense_details(
        self,
        user_id: UUID,
        from_month: date,
        months: int,
        plan_id: UUID | None = None,
    ) -> dict[date, list[ForecastFlowItemDTO]]:
        month_list = [
            Month.from_any_date(from_month).add_months(i).value for i in range(months)
        ]
        details: dict[date, list[ForecastFlowItemDTO]] = {
            month: [] for month in month_list
        }
        if not month_list:
            return details
        start = month_list[0]
        end_exclusive = Month.from_any_date(month_list[-1]).add_months(1).value

        transaction_stmt = (
            select(Transaction, Category)
            .join(Category, Category.id == Transaction.category_id)
            .where(
                Transaction.user_id == user_id,
                Transaction.direction == TransactionDirection.EXPENSE,
                Transaction.competency_month >= start,
                Transaction.competency_month < end_exclusive,
            )
        )
        if plan_id is not None:
            transaction_stmt = transaction_stmt.join(
                PlanTransaction,
                PlanTransaction.transaction_id == Transaction.id,
            ).where(PlanTransaction.plan_id == plan_id)
        for row, category in self.db.execute(transaction_stmt):
            details[row.competency_month].append(
                ForecastFlowItemDTO(
                    month=row.competency_month,
                    source_id=row.id,
                    source_type="TRANSACTION",
                    source_label="Lançamento",
                    description=row.description or category.name,
                    category_name=category.name,
                    detail=f"Realizado em {row.occurred_on.strftime('%d/%m/%Y')}",
                    amount_cents=row.amount_cents,
                    edit_url=f"/app/transactions?month={row.competency_month.strftime('%Y-%m')}",
                )
            )

        recurring_stmt = (
            select(RecurringRule, Category)
            .join(Category, Category.id == RecurringRule.category_id)
            .where(
                RecurringRule.user_id == user_id,
                RecurringRule.direction == TransactionDirection.EXPENSE,
                RecurringRule.start_month <= month_list[-1],
                (
                    RecurringRule.end_month.is_(None)
                    | (RecurringRule.end_month >= start)
                ),
            )
        )
        if plan_id is not None:
            recurring_stmt = recurring_stmt.join(
                PlanRecurringRule,
                PlanRecurringRule.recurring_rule_id == RecurringRule.id,
            ).where(PlanRecurringRule.plan_id == plan_id)
        for row, category in self.db.execute(recurring_stmt):
            for month in month_list:
                if month < row.start_month or (
                    row.end_month is not None and month > row.end_month
                ):
                    continue
                details[month].append(
                    ForecastFlowItemDTO(
                        month=month,
                        source_id=row.id,
                        source_type="RECURRING",
                        source_label="Recorrência",
                        description=row.name,
                        category_name=category.name,
                        detail=f"Previsto para o dia {row.day_of_month}",
                        amount_cents=row.amount_cents,
                        edit_url="/app/transactions/recurrences",
                    )
                )

        installment_stmt = (
            select(Installment, Category)
            .join(Category, Category.id == Installment.category_id)
            .where(
                Installment.user_id == user_id,
                Installment.first_competency_month <= month_list[-1],
            )
        )
        if plan_id is not None:
            installment_stmt = installment_stmt.join(
                PlanInstallment,
                PlanInstallment.installment_id == Installment.id,
            ).where(PlanInstallment.plan_id == plan_id)
        month_set = set(month_list)
        for row, category in self.db.execute(installment_stmt):
            first = Month.from_any_date(row.first_competency_month)
            for index in range(row.total_parts):
                month = first.add_months(index).value
                if month not in month_set:
                    continue
                details[month].append(
                    ForecastFlowItemDTO(
                        month=month,
                        source_id=row.id,
                        source_type="INSTALLMENT",
                        source_label="Parcela",
                        description=row.description or "Compra parcelada",
                        category_name=category.name,
                        detail=f"Parcela {index + 1}/{row.total_parts}",
                        amount_cents=row.part_amount_cents,
                        edit_url="/app/transactions/installments",
                    )
                )

        debt_stmt = (
            select(DebtPlan, Debt)
            .join(Debt, Debt.id == DebtPlan.debt_id)
            .where(
                DebtPlan.user_id == user_id,
                DebtPlan.start_month <= month_list[-1],
                (DebtPlan.end_month.is_(None) | (DebtPlan.end_month >= start)),
            )
        )
        for row, debt in self.db.execute(debt_stmt):
            for month in month_list:
                if month < row.start_month or (
                    row.end_month is not None and month > row.end_month
                ):
                    continue
                details[month].append(
                    ForecastFlowItemDTO(
                        month=month,
                        source_id=row.id,
                        source_type="DEBT",
                        source_label="Dívida",
                        description=debt.name,
                        category_name="Quitação de dívidas",
                        detail=debt.creditor or "Pagamento planejado",
                        amount_cents=row.monthly_payment_cents,
                        edit_url="/app/prosperity#dividas",
                    )
                )

        self._sort_details(details)
        return details

    def build_income_details(
        self,
        user_id: UUID,
        from_month: date,
        months: int,
        plan_id: UUID | None = None,
    ) -> dict[date, list[ForecastFlowItemDTO]]:
        month_list = [
            Month.from_any_date(from_month).add_months(i).value for i in range(months)
        ]
        details: dict[date, list[ForecastFlowItemDTO]] = {
            month: [] for month in month_list
        }
        if not month_list:
            return details
        start = month_list[0]
        end_exclusive = Month.from_any_date(month_list[-1]).add_months(1).value

        transaction_stmt = (
            select(Transaction, Category)
            .join(Category, Category.id == Transaction.category_id)
            .where(
                Transaction.user_id == user_id,
                Transaction.direction == TransactionDirection.INCOME,
                Transaction.competency_month >= start,
                Transaction.competency_month < end_exclusive,
            )
        )
        if plan_id is not None:
            transaction_stmt = transaction_stmt.join(
                PlanTransaction,
                PlanTransaction.transaction_id == Transaction.id,
            ).where(PlanTransaction.plan_id == plan_id)
        for row, category in self.db.execute(transaction_stmt):
            details[row.competency_month].append(
                ForecastFlowItemDTO(
                    month=row.competency_month,
                    source_id=row.id,
                    source_type="TRANSACTION",
                    source_label="Lançamento",
                    description=row.description or category.name,
                    category_name=category.name,
                    detail=f"Recebido em {row.occurred_on.strftime('%d/%m/%Y')}",
                    amount_cents=row.amount_cents,
                    edit_url=f"/app/transactions?month={row.competency_month.strftime('%Y-%m')}",
                )
            )

        recurring_stmt = (
            select(RecurringRule, Category)
            .join(Category, Category.id == RecurringRule.category_id)
            .where(
                RecurringRule.user_id == user_id,
                RecurringRule.direction == TransactionDirection.INCOME,
                RecurringRule.start_month <= month_list[-1],
                (
                    RecurringRule.end_month.is_(None)
                    | (RecurringRule.end_month >= start)
                ),
            )
        )
        if plan_id is not None:
            recurring_stmt = recurring_stmt.join(
                PlanRecurringRule,
                PlanRecurringRule.recurring_rule_id == RecurringRule.id,
            ).where(PlanRecurringRule.plan_id == plan_id)
        for row, category in self.db.execute(recurring_stmt):
            for month in month_list:
                if month < row.start_month or (
                    row.end_month is not None and month > row.end_month
                ):
                    continue
                details[month].append(
                    ForecastFlowItemDTO(
                        month=month,
                        source_id=row.id,
                        source_type="RECURRING",
                        source_label="Recorrência",
                        description=row.name,
                        category_name=category.name,
                        detail=f"Previsto para o dia {row.day_of_month}",
                        amount_cents=row.amount_cents,
                        edit_url="/app/transactions/recurrences",
                    )
                )

        self._sort_details(details)
        return details

    def _sort_details(self, details: dict[date, list[ForecastFlowItemDTO]]) -> None:
        for month_items in details.values():
            month_items.sort(
                key=lambda item: (
                    self._SOURCE_ORDER.get(item.source_type, 99),
                    (item.category_name or "Sem categoria").casefold(),
                    item.description.casefold(),
                )
            )

    @staticmethod
    def _add_income(
        flow_map: dict[date, MonthlyFlow], month: date, amount: int
    ) -> None:
        prev = flow_map[month]
        flow_map[month] = MonthlyFlow(
            month, prev.income_cents + amount, prev.expense_cents
        )

    @staticmethod
    def _add_expense(
        flow_map: dict[date, MonthlyFlow], month: date, amount: int
    ) -> None:
        prev = flow_map[month]
        flow_map[month] = MonthlyFlow(
            month, prev.income_cents, prev.expense_cents + amount
        )

    def _aggregate_transactions(
        self,
        user_id: UUID,
        month_list: list[date],
        flow_map: dict[date, MonthlyFlow],
        *,
        plan_id: UUID | None = None,
    ) -> None:
        start = month_list[0]
        end = Month.from_any_date(month_list[-1]).add_months(1).value
        stmt = select(Transaction).where(
            and_(
                Transaction.user_id == user_id,
                Transaction.competency_month >= start,
                Transaction.competency_month < end,
            )
        )
        if plan_id is not None:
            stmt = stmt.join(
                PlanTransaction,
                PlanTransaction.transaction_id == Transaction.id,
            ).where(PlanTransaction.plan_id == plan_id)
        for row in self.db.scalars(stmt):
            if row.competency_month not in flow_map:
                continue
            if row.direction == TransactionDirection.INCOME:
                self._add_income(flow_map, row.competency_month, row.amount_cents)
            else:
                self._add_expense(flow_map, row.competency_month, row.amount_cents)

    def _aggregate_recurring(
        self,
        user_id: UUID,
        month_list: list[date],
        flow_map: dict[date, MonthlyFlow],
        *,
        plan_id: UUID | None = None,
    ) -> None:
        start = month_list[0]
        end = month_list[-1]
        stmt = select(RecurringRule).where(
            and_(
                RecurringRule.user_id == user_id,
                RecurringRule.start_month <= end,
                (
                    RecurringRule.end_month.is_(None)
                    | (RecurringRule.end_month >= start)
                ),
            )
        )
        if plan_id is not None:
            stmt = stmt.join(
                PlanRecurringRule,
                PlanRecurringRule.recurring_rule_id == RecurringRule.id,
            ).where(PlanRecurringRule.plan_id == plan_id)
        for row in self.db.scalars(stmt):
            for month in month_list:
                if month < row.start_month:
                    continue
                if row.end_month is not None and month > row.end_month:
                    continue
                if row.direction == TransactionDirection.INCOME:
                    self._add_income(flow_map, month, row.amount_cents)
                else:
                    self._add_expense(flow_map, month, row.amount_cents)

    def _aggregate_installments(
        self,
        user_id: UUID,
        month_list: list[date],
        flow_map: dict[date, MonthlyFlow],
        *,
        plan_id: UUID | None = None,
    ) -> None:
        last = month_list[-1]
        stmt = select(Installment).where(
            and_(
                Installment.user_id == user_id,
                Installment.first_competency_month <= last,
            )
        )
        if plan_id is not None:
            stmt = stmt.join(
                PlanInstallment,
                PlanInstallment.installment_id == Installment.id,
            ).where(PlanInstallment.plan_id == plan_id)
        month_set = set(month_list)
        for row in self.db.scalars(stmt):
            first = Month.from_any_date(row.first_competency_month)
            for idx in range(row.total_parts):
                month = first.add_months(idx).value
                if month in month_set:
                    self._add_expense(flow_map, month, row.part_amount_cents)

    def _aggregate_debt_plans(
        self, user_id: UUID, month_list: list[date], flow_map: dict[date, MonthlyFlow]
    ) -> None:
        start = month_list[0]
        end = month_list[-1]
        stmt = select(DebtPlan).where(
            and_(
                DebtPlan.user_id == user_id,
                DebtPlan.start_month <= end,
                (DebtPlan.end_month.is_(None) | (DebtPlan.end_month >= start)),
            )
        )
        for row in self.db.scalars(stmt):
            for month in month_list:
                if month < row.start_month:
                    continue
                if row.end_month is not None and month > row.end_month:
                    continue
                self._add_expense(flow_map, month, row.monthly_payment_cents)
