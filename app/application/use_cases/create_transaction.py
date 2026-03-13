from uuid import UUID

from app.application.dto.transaction_dto import CreateTransactionDTO, TransactionReadDTO
from app.application.ports.repositories import TransactionRepositoryPort


class CreateTransactionUseCase:
    def __init__(self, repo: TransactionRepositoryPort) -> None:
        self.repo = repo

    def execute(self, *, user_id: UUID, payload: CreateTransactionDTO) -> TransactionReadDTO:
        return TransactionReadDTO.model_validate(self.repo.create(user_id=user_id, payload=payload))

