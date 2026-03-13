from io import BytesIO
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.application.dto.import_dto import ApplyImportPayloadDTO
from app.application.use_cases.apply_import_to_transactions import ApplyImportToTransactionsUseCase
from app.application.use_cases.import_csv_to_staging import ImportCSVToStagingUseCase
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import account, category, credit_card, debt, debt_plan, external_transaction, financial_plan
from app.infrastructure.db.models import import_file as import_file_model
from app.infrastructure.db.models import installment, notification, plan_installment, plan_recurring_rule, plan_transaction
from app.infrastructure.db.models import recurring_rule, transaction, user
from app.infrastructure.db.models.account import Account
from app.infrastructure.db.models.category import Category
from app.infrastructure.db.models.enums import AccountType, CategoryKind, ExternalTransactionReviewStatus, ImportFileStatus
from app.infrastructure.db.models.financial_plan import FinancialPlan
from app.infrastructure.db.models.plan_transaction import PlanTransaction
from app.infrastructure.db.models.transaction import Transaction
from app.infrastructure.db.models.user import User
from app.infrastructure.importers.credit_card_csv_importer import CreditCardCSVImporter
from app.infrastructure.repositories.external_tx_repo import SQLAlchemyExternalTransactionRepository
from app.infrastructure.repositories.import_file_repo import SQLAlchemyImportFileRepository

# Keep imports referenced so SQLAlchemy metadata has all tables.
_ = (
    account,
    category,
    credit_card,
    debt,
    debt_plan,
    external_transaction,
    financial_plan,
    import_file_model,
    installment,
    notification,
    plan_installment,
    plan_recurring_rule,
    plan_transaction,
    recurring_rule,
    transaction,
    user,
)


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def test_import_deduplicates_and_apply_marks_applied() -> None:
    db = _build_session()
    try:
        user_row = User(id=uuid4(), email="import@test.local", password_hash="hash")
        account_row = Account(id=uuid4(), user_id=user_row.id, name="Conta principal", type=AccountType.BANK)
        category_row = Category(id=uuid4(), user_id=user_row.id, name="Alimentacao", kind=CategoryKind.EXPENSE)
        plan_row = FinancialPlan(id=uuid4(), user_id=user_row.id, name="Plano A")
        db.add_all([user_row, account_row, category_row, plan_row])
        db.commit()

        csv_payload = (
            "date,description,amount\n"
            "2026-02-10,Super Mercado,-123,45\n"
            "2026-02-10,Super Mercado,-123,45\n"
            "2026-02-11,Padaria,-20.00\n"
        ).encode("utf-8")
        # Decimal comma line uses extra separator, so use semicolon CSV for that row.
        csv_payload = (
            "date;description;amount\n"
            "2026-02-10;Super Mercado;-123,45\n"
            "2026-02-10;Super Mercado;-123,45\n"
            "2026-02-11;Padaria;-20.00\n"
        ).encode("utf-8")

        import_use_case = ImportCSVToStagingUseCase(
            importer=CreditCardCSVImporter(),
            import_file_repo=SQLAlchemyImportFileRepository(db),
            external_tx_repo=SQLAlchemyExternalTransactionRepository(db),
        )
        summary = import_use_case.execute(
            user_id=user_row.id,
            filename="cartao.csv",
            stream=BytesIO(csv_payload),
            card_id=None,
        )

        assert summary.total_linhas == 3
        assert summary.importadas == 2
        assert summary.duplicadas == 1
        assert summary.com_erro == 0

        staged = list(
            db.scalars(
                select(external_transaction.ExternalTransaction).where(
                    external_transaction.ExternalTransaction.import_file_id == summary.import_file_id
                )
            )
        )
        assert len(staged) == 2

        second_summary = import_use_case.execute(
            user_id=user_row.id,
            filename="cartao_repetido.csv",
            stream=BytesIO(csv_payload),
            card_id=None,
        )
        assert second_summary.importadas == 0
        assert second_summary.duplicadas == 3

        apply_use_case = ApplyImportToTransactionsUseCase(
            db=db,
            import_file_repo=SQLAlchemyImportFileRepository(db),
            external_tx_repo=SQLAlchemyExternalTransactionRepository(db),
        )
        apply_result = apply_use_case.execute(
            user_id=user_row.id,
            import_file_id=summary.import_file_id,
            payload=ApplyImportPayloadDTO(
                default_account_id=account_row.id,
                default_category_id=category_row.id,
                approve_all=True,
            ),
            active_plan_id=plan_row.id,
        )

        assert apply_result.applied_count == 2
        assert apply_result.skipped_count == 0

        tx_rows = list(db.scalars(select(Transaction).where(Transaction.user_id == user_row.id)))
        assert len(tx_rows) == 2
        assert all(item.amount_cents > 0 for item in tx_rows)

        plan_links = list(db.scalars(select(PlanTransaction).where(PlanTransaction.plan_id == plan_row.id)))
        assert len(plan_links) == 2

        refreshed_import = db.get(import_file_model.ImportFile, summary.import_file_id)
        assert refreshed_import is not None
        assert refreshed_import.status == ImportFileStatus.APPLIED

        final_review_states = [
            item.review_status
            for item in db.scalars(
                select(external_transaction.ExternalTransaction).where(
                    external_transaction.ExternalTransaction.import_file_id == summary.import_file_id
                )
            )
        ]
        assert final_review_states
        assert all(status_item == ExternalTransactionReviewStatus.APPLIED for status_item in final_review_states)
    finally:
        db.close()
