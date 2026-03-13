from datetime import date
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.application.dto.transaction_dto import CreateTransactionDTO, UpdateTransactionDTO
from app.domain.services.forecast_engine import MonthlyFlow
from app.domain.value_objects.month import Month
from app.infrastructure.db.models.account import Account
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

    def update(self, user_id: UUID, transaction_id: UUID, payload: UpdateTransactionDTO) -> Transaction:
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

    def list_by_month(self, user_id: UUID, month: date, plan_id: UUID | None = None) -> list[Transaction]:
        normalized = Month.from_any_date(month).value
        stmt = (
            select(Transaction)
            .where(and_(Transaction.user_id == user_id, Transaction.competency_month == normalized))
            .order_by(Transaction.occurred_on.desc(), Transaction.created_at.desc())
        )
        if plan_id is not None:
            stmt = stmt.join(
                PlanTransaction,
                PlanTransaction.transaction_id == Transaction.id,
            ).where(PlanTransaction.plan_id == plan_id)
        return list(self.db.scalars(stmt))


class SQLAlchemyForecastRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def sum_account_initial_balances(self, user_id: UUID) -> int:
        total = self.db.scalar(
            select(func.coalesce(func.sum(Account.initial_balance_cents), 0)).where(Account.user_id == user_id)
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
        month_list = [Month.from_any_date(from_month).add_months(i).value for i in range(months)]
        flow_map = {m: MonthlyFlow(month=m, income_cents=0, expense_cents=0) for m in month_list}
        if not month_list:
            return flow_map

        self._aggregate_transactions(user_id, month_list, flow_map, plan_id=plan_id)
        self._aggregate_recurring(user_id, month_list, flow_map, plan_id=plan_id)
        self._aggregate_installments(user_id, month_list, flow_map, plan_id=plan_id)
        if plan_id is None:
            self._aggregate_debt_plans(user_id, month_list, flow_map)
        return flow_map

    @staticmethod
    def _add_income(flow_map: dict[date, MonthlyFlow], month: date, amount: int) -> None:
        prev = flow_map[month]
        flow_map[month] = MonthlyFlow(month, prev.income_cents + amount, prev.expense_cents)

    @staticmethod
    def _add_expense(flow_map: dict[date, MonthlyFlow], month: date, amount: int) -> None:
        prev = flow_map[month]
        flow_map[month] = MonthlyFlow(month, prev.income_cents, prev.expense_cents + amount)

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
                (RecurringRule.end_month.is_(None) | (RecurringRule.end_month >= start)),
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
            and_(Installment.user_id == user_id, Installment.first_competency_month <= last)
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

    def _aggregate_debt_plans(self, user_id: UUID, month_list: list[date], flow_map: dict[date, MonthlyFlow]) -> None:
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
