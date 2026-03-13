from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.enums import ImportFileStatus
from app.infrastructure.db.models.import_file import ImportFile


class SQLAlchemyImportFileRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        user_id: UUID,
        source: str,
        filename: str | None,
        note: str | None = None,
    ) -> ImportFile:
        row = ImportFile(user_id=user_id, source=source, filename=filename, note=note)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_for_user(self, *, import_file_id: UUID, user_id: UUID) -> ImportFile | None:
        return self.db.scalar(
            select(ImportFile).where(ImportFile.id == import_file_id, ImportFile.user_id == user_id)
        )

    def set_status(
        self,
        *,
        import_file: ImportFile,
        status: ImportFileStatus,
        note: str | None = None,
    ) -> ImportFile:
        import_file.status = status
        if note is not None:
            import_file.note = note
        self.db.add(import_file)
        self.db.commit()
        self.db.refresh(import_file)
        return import_file
