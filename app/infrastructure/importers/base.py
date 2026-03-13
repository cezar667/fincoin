from abc import ABC, abstractmethod
from io import BufferedIOBase
from uuid import UUID

from app.application.dto.import_dto import CSVColumnMappingDTO, CSVImportParseResultDTO


class BaseCSVImporter(ABC):
    @abstractmethod
    def parse(
        self,
        *,
        stream: BufferedIOBase,
        user_id: UUID,
        import_file_id: UUID,
        card_id: UUID | None,
        mapping: CSVColumnMappingDTO | None = None,
    ) -> CSVImportParseResultDTO:
        raise NotImplementedError
