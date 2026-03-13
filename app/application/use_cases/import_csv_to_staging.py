from io import BufferedIOBase
from uuid import UUID

from app.application.dto.import_dto import CSVColumnMappingDTO, ImportCSVSummaryDTO
from app.infrastructure.db.models.enums import ImportFileStatus
from app.infrastructure.db.models.external_transaction import ExternalTransaction
from app.infrastructure.importers.base import BaseCSVImporter
from app.infrastructure.repositories.external_tx_repo import SQLAlchemyExternalTransactionRepository
from app.infrastructure.repositories.import_file_repo import SQLAlchemyImportFileRepository


class ImportCSVToStagingUseCase:
    def __init__(
        self,
        *,
        importer: BaseCSVImporter,
        import_file_repo: SQLAlchemyImportFileRepository,
        external_tx_repo: SQLAlchemyExternalTransactionRepository,
    ) -> None:
        self.importer = importer
        self.import_file_repo = import_file_repo
        self.external_tx_repo = external_tx_repo

    def execute(
        self,
        *,
        user_id: UUID,
        filename: str,
        stream: BufferedIOBase,
        card_id: UUID | None,
        mapping: CSVColumnMappingDTO | None = None,
    ) -> ImportCSVSummaryDTO:
        import_file = self.import_file_repo.create(
            user_id=user_id,
            source="csv_upload",
            filename=filename,
        )
        parsed = self.importer.parse(
            stream=stream,
            user_id=user_id,
            import_file_id=import_file.id,
            card_id=card_id,
            mapping=mapping,
        )

        hashes = {item.hash for item in parsed.items}
        existing_hashes = self.external_tx_repo.find_existing_hashes(
            user_id=user_id,
            source="csv",
            hashes=hashes,
        )

        to_insert = [item for item in parsed.items if item.hash not in existing_hashes]
        db_duplicate_count = len(parsed.items) - len(to_insert)

        rows = [ExternalTransaction(**item.model_dump()) for item in to_insert]
        inserted_count = self.external_tx_repo.bulk_create(rows)

        summary = ImportCSVSummaryDTO(
            import_file_id=import_file.id,
            total_linhas=parsed.total_linhas,
            importadas=inserted_count,
            duplicadas=parsed.duplicadas + db_duplicate_count + max(0, len(to_insert) - inserted_count),
            com_erro=parsed.com_erro,
            errors=parsed.errors,
        )

        # TODO: aplicar import_rules (quando existirem) antes da revisao manual.
        note = (
            f"total={summary.total_linhas}; importadas={summary.importadas}; "
            f"duplicadas={summary.duplicadas}; erros={summary.com_erro}"
        )
        status = ImportFileStatus.REVIEWING if summary.total_linhas > 0 else ImportFileStatus.IMPORTED
        self.import_file_repo.set_status(import_file=import_file, status=status, note=note)
        return summary
