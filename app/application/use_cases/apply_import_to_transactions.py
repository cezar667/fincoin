from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.dto.import_dto import ApplyImportPayloadDTO, ApplyImportResultDTO
from app.infrastructure.db.models.account import Account
from app.infrastructure.db.models.category import Category
from app.infrastructure.db.models.enums import CategoryKind, ImportFileStatus, TransactionDirection
from app.infrastructure.db.models.financial_plan import FinancialPlan
from app.infrastructure.db.models.plan_transaction import PlanTransaction
from app.infrastructure.db.models.transaction import Transaction
from app.infrastructure.importers.utils import first_month_day
from app.infrastructure.repositories.external_tx_repo import SQLAlchemyExternalTransactionRepository
from app.infrastructure.repositories.import_file_repo import SQLAlchemyImportFileRepository


class ApplyImportToTransactionsUseCase:
    def __init__(
        self,
        *,
        db: Session,
        import_file_repo: SQLAlchemyImportFileRepository,
        external_tx_repo: SQLAlchemyExternalTransactionRepository,
    ) -> None:
        self.db = db
        self.import_file_repo = import_file_repo
        self.external_tx_repo = external_tx_repo

    def execute(
        self,
        *,
        user_id: UUID,
        import_file_id: UUID,
        payload: ApplyImportPayloadDTO,
        active_plan_id: UUID | None = None,
    ) -> ApplyImportResultDTO:
        import_file = self.import_file_repo.get_for_user(import_file_id=import_file_id, user_id=user_id)
        if import_file is None:
            raise ValueError("Arquivo de importacao nao encontrado")

        default_account = self._require_account(user_id=user_id, account_id=payload.default_account_id)
        default_category = None
        if payload.default_category_id is not None:
            default_category = self._require_category(user_id=user_id, category_id=payload.default_category_id)

        plan = self._resolve_active_plan(user_id=user_id, active_plan_id=active_plan_id)
        candidates = self.external_tx_repo.list_for_apply(
            user_id=user_id,
            import_file_id=import_file_id,
            approve_all=payload.approve_all,
            approved_ids=payload.approved_ids,
        )
        if not candidates:
            remaining = self.external_tx_repo.count_open_for_apply(user_id=user_id, import_file_id=import_file_id)
            if remaining == 0:
                import_file.status = ImportFileStatus.APPLIED
                self.db.add(import_file)
                self.db.commit()
            return ApplyImportResultDTO(applied_count=0, skipped_count=0, errors=[])

        applied_external_ids: list[UUID] = []
        errors: list[str] = []

        for row in candidates:
            try:
                with self.db.begin_nested():
                    account = self._resolve_account_for_row(user_id=user_id, default_account=default_account, mapped_id=row.mapped_account_id)
                    category = self._resolve_category_for_row(
                        user_id=user_id,
                        direction=row.direction,
                        default_category=default_category,
                        mapped_id=row.mapped_category_id,
                    )
                    tx = Transaction(
                        user_id=user_id,
                        account_id=account.id,
                        category_id=category.id,
                        description=row.normalized_description,
                        amount_cents=abs(row.amount_cents),
                        direction=row.direction,
                        occurred_on=row.normalized_date,
                        competency_month=first_month_day(row.normalized_date),
                    )
                    self.db.add(tx)
                    self.db.flush()
                    if plan is not None:
                        self.db.add(PlanTransaction(plan_id=plan.id, transaction_id=tx.id))
                applied_external_ids.append(row.id)
            except Exception as exc:
                errors.append(f"{row.id}: {exc}")

        self.external_tx_repo.mark_as_applied(user_id=user_id, external_tx_ids=applied_external_ids, commit=False)
        remaining = self.external_tx_repo.count_open_for_apply(user_id=user_id, import_file_id=import_file_id)
        new_status = ImportFileStatus.APPLIED if remaining == 0 else ImportFileStatus.REVIEWING
        import_file.status = new_status
        self.db.add(import_file)
        self.db.commit()

        return ApplyImportResultDTO(
            applied_count=len(applied_external_ids),
            skipped_count=len(candidates) - len(applied_external_ids),
            errors=errors,
        )

    def _resolve_active_plan(self, *, user_id: UUID, active_plan_id: UUID | None) -> FinancialPlan | None:
        if active_plan_id is None:
            return None
        return self.db.scalar(
            select(FinancialPlan).where(FinancialPlan.id == active_plan_id, FinancialPlan.user_id == user_id)
        )

    def _resolve_account_for_row(self, *, user_id: UUID, default_account: Account, mapped_id: UUID | None) -> Account:
        if mapped_id is None:
            return default_account
        return self._require_account(user_id=user_id, account_id=mapped_id)

    def _resolve_category_for_row(
        self,
        *,
        user_id: UUID,
        direction: TransactionDirection,
        default_category: Category | None,
        mapped_id: UUID | None,
    ) -> Category:
        selected: Category | None = default_category
        if mapped_id is not None:
            selected = self._require_category(user_id=user_id, category_id=mapped_id)

        target_kind = CategoryKind.INCOME if direction == TransactionDirection.INCOME else CategoryKind.EXPENSE
        if selected is not None:
            if selected.kind != target_kind:
                raise ValueError("Categoria nao corresponde ao tipo da transacao")
            return selected
        return self._get_or_create_uncategorized(user_id=user_id, kind=target_kind)

    def _get_or_create_uncategorized(self, *, user_id: UUID, kind: CategoryKind) -> Category:
        row = self.db.scalar(
            select(Category).where(
                Category.user_id == user_id,
                Category.kind == kind,
                Category.name == "Sem categoria",
            )
        )
        if row is None:
            row = Category(user_id=user_id, name="Sem categoria", kind=kind)
            self.db.add(row)
            self.db.flush()
        return row

    def _require_account(self, *, user_id: UUID, account_id: UUID) -> Account:
        row = self.db.get(Account, account_id)
        if row is None or row.user_id != user_id:
            raise ValueError("Conta padrao invalida")
        return row

    def _require_category(self, *, user_id: UUID, category_id: UUID) -> Category:
        row = self.db.get(Category, category_id)
        if row is None or row.user_id != user_id:
            raise ValueError("Categoria invalida")
        return row
