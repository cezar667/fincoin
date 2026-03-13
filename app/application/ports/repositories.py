from datetime import date
from typing import Protocol
from uuid import UUID

from app.application.dto.transaction_dto import CreateTransactionDTO, UpdateTransactionDTO
from app.domain.services.forecast_engine import MonthlyFlow
from app.infrastructure.db.models.transaction import Transaction


class TransactionRepositoryPort(Protocol):
    def create(self, user_id: UUID, payload: CreateTransactionDTO) -> Transaction: ...

    def update(self, user_id: UUID, transaction_id: UUID, payload: UpdateTransactionDTO) -> Transaction: ...

    def delete(self, user_id: UUID, transaction_id: UUID) -> None: ...

    def list_by_month(self, user_id: UUID, month: date, plan_id: UUID | None = None) -> list[Transaction]: ...


class ForecastRepositoryPort(Protocol):
    def build_flow_map(
        self,
        user_id: UUID,
        from_month: date,
        months: int,
        plan_id: UUID | None = None,
    ) -> dict[date, MonthlyFlow]: ...

    def sum_account_initial_balances(self, user_id: UUID) -> int: ...
