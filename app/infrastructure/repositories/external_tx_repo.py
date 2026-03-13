from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.db.models.enums import ExternalTransactionReviewStatus
from app.infrastructure.db.models.external_transaction import ExternalTransaction


class SQLAlchemyExternalTransactionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def find_existing_hashes(self, *, user_id: UUID, source: str, hashes: set[str]) -> set[str]:
        if not hashes:
            return set()
        stmt = select(ExternalTransaction.hash).where(
            ExternalTransaction.user_id == user_id,
            ExternalTransaction.source == source,
            ExternalTransaction.hash.in_(list(hashes)),
        )
        return set(self.db.scalars(stmt))

    def bulk_create(self, rows: list[ExternalTransaction]) -> int:
        if not rows:
            return 0
        inserted = 0
        for row in rows:
            try:
                with self.db.begin_nested():
                    self.db.add(row)
                    self.db.flush()
                inserted += 1
            except IntegrityError:
                continue
        self.db.commit()
        return inserted

    def list_by_import_file(
        self,
        *,
        user_id: UUID,
        import_file_id: UUID,
        status: ExternalTransactionReviewStatus | None = None,
    ) -> list[ExternalTransaction]:
        stmt = self._base_import_stmt(user_id=user_id, import_file_id=import_file_id)
        if status is not None:
            stmt = stmt.where(ExternalTransaction.review_status == status)
        stmt = stmt.order_by(ExternalTransaction.normalized_date.asc(), ExternalTransaction.created_at.asc())
        return list(self.db.scalars(stmt))

    def count_by_review_status(self, *, user_id: UUID, import_file_id: UUID) -> dict[str, int]:
        counts = {item.value: 0 for item in ExternalTransactionReviewStatus}
        stmt = (
            select(ExternalTransaction.review_status, func.count())
            .where(
                ExternalTransaction.user_id == user_id,
                ExternalTransaction.import_file_id == import_file_id,
            )
            .group_by(ExternalTransaction.review_status)
        )
        for status, amount in self.db.execute(stmt):
            counts[status.value] = int(amount)
        return counts

    def get_for_user(self, *, external_tx_id: UUID, user_id: UUID) -> ExternalTransaction | None:
        return self.db.scalar(
            select(ExternalTransaction).where(
                ExternalTransaction.id == external_tx_id,
                ExternalTransaction.user_id == user_id,
            )
        )

    def set_mapping(
        self,
        *,
        external_tx: ExternalTransaction,
        category_id: UUID | None,
        account_id: UUID | None,
    ) -> ExternalTransaction:
        if category_id is not None:
            external_tx.mapped_category_id = category_id
        if account_id is not None:
            external_tx.mapped_account_id = account_id
        self.db.add(external_tx)
        self.db.commit()
        self.db.refresh(external_tx)
        return external_tx

    def reject(self, *, external_tx: ExternalTransaction) -> ExternalTransaction:
        external_tx.review_status = ExternalTransactionReviewStatus.REJECTED
        self.db.add(external_tx)
        self.db.commit()
        self.db.refresh(external_tx)
        return external_tx

    def list_for_apply(
        self,
        *,
        user_id: UUID,
        import_file_id: UUID,
        approve_all: bool,
        approved_ids: list[UUID],
    ) -> list[ExternalTransaction]:
        allowed = [ExternalTransactionReviewStatus.PENDING, ExternalTransactionReviewStatus.APPROVED]
        stmt = self._base_import_stmt(user_id=user_id, import_file_id=import_file_id).where(
            ExternalTransaction.review_status.in_(allowed)
        )
        if not approve_all:
            if not approved_ids:
                return []
            stmt = stmt.where(ExternalTransaction.id.in_(approved_ids))
        stmt = stmt.order_by(ExternalTransaction.normalized_date.asc(), ExternalTransaction.created_at.asc())
        return list(self.db.scalars(stmt))

    def mark_as_applied(self, *, user_id: UUID, external_tx_ids: list[UUID], commit: bool = True) -> None:
        if not external_tx_ids:
            return
        self.db.execute(
            update(ExternalTransaction)
            .where(
                ExternalTransaction.user_id == user_id,
                ExternalTransaction.id.in_(external_tx_ids),
            )
            .values(review_status=ExternalTransactionReviewStatus.APPLIED)
        )
        if commit:
            self.db.commit()

    def count_open_for_apply(self, *, user_id: UUID, import_file_id: UUID) -> int:
        stmt = select(func.count()).where(
            ExternalTransaction.user_id == user_id,
            ExternalTransaction.import_file_id == import_file_id,
            ExternalTransaction.review_status.in_(
                [ExternalTransactionReviewStatus.PENDING, ExternalTransactionReviewStatus.APPROVED]
            ),
        )
        return int(self.db.scalar(stmt) or 0)

    @staticmethod
    def _base_import_stmt(*, user_id: UUID, import_file_id: UUID) -> Select[tuple[ExternalTransaction]]:
        return select(ExternalTransaction).where(
            ExternalTransaction.user_id == user_id,
            ExternalTransaction.import_file_id == import_file_id,
        )
