from uuid import UUID

from app.application.dto.transaction_dto import TransactionReadDTO, UpdateTransactionDTO
from app.application.ports.repositories import TransactionRepositoryPort


class UpdateTransactionUseCase:
    def __init__(self, repo: TransactionRepositoryPort) -> None:
        self.repo = repo

    def execute(
        self,
        *,
        user_id: UUID,
        transaction_id: UUID,
        payload: UpdateTransactionDTO,
    ) -> TransactionReadDTO:
        return TransactionReadDTO.model_validate(
            self.repo.update(user_id=user_id, transaction_id=transaction_id, payload=payload)
        )

