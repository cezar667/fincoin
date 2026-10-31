"""One-time, guarded transfer of a FinSight SQLite database to PostgreSQL."""

import argparse
from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine, func, select
from sqlalchemy.engine import Connection, Engine

from app.infrastructure.db import models as _models  # noqa: F401
from app.infrastructure.db.base import Base
from app.infrastructure.settings.config import get_settings

BATCH_SIZE = 500


def _batches(rows: Iterator[dict[str, object]]) -> Iterator[list[dict[str, object]]]:
    batch: list[dict[str, object]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == BATCH_SIZE:
            yield batch
            batch = []
    if batch:
        yield batch


def _target_has_data(connection: Connection) -> bool:
    for table in Base.metadata.sorted_tables:
        if connection.scalar(select(func.count()).select_from(table)):
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transfere uma base SQLite FinSight para um PostgreSQL vazio."
    )
    parser.add_argument(
        "--source-url",
        required=True,
        help="URL SQLAlchemy do SQLite de origem, por exemplo sqlite+pysqlite:////transfer/finsight.db",
    )
    args = parser.parse_args()
    if not args.source_url.startswith("sqlite"):
        parser.error("A origem precisa ser uma URL SQLite.")

    target_url = get_settings().database_url
    if not target_url.startswith("postgresql"):
        parser.error("DATABASE_URL precisa apontar para PostgreSQL no destino.")

    source_engine: Engine = create_engine(args.source_url, future=True)
    target_engine: Engine = create_engine(target_url, future=True)
    source_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)
    missing_tables = [
        table.name
        for table in Base.metadata.sorted_tables
        if table.name not in source_metadata.tables
    ]
    if missing_tables:
        parser.error(
            "O SQLite não tem todas as tabelas esperadas: " + ", ".join(missing_tables)
        )

    try:
        with target_engine.begin() as target_connection:
            if _target_has_data(target_connection):
                parser.error(
                    "O PostgreSQL de destino já tem dados. "
                    "A transferência foi interrompida para não misturar informações."
                )
            for target_table in Base.metadata.sorted_tables:
                source_table = source_metadata.tables[target_table.name]
                column_names = [
                    column.name
                    for column in target_table.columns
                    if column.name in source_table.c
                ]
                with source_engine.connect() as source_connection:
                    result = source_connection.execute(
                        select(*(source_table.c[name] for name in column_names))
                    )
                    row_count = 0
                    rows = (dict(row) for row in result.mappings())
                    for batch in _batches(rows):
                        target_connection.execute(target_table.insert(), batch)
                        row_count += len(batch)
                print(f"{target_table.name}: {row_count} registros transferidos")
    finally:
        source_engine.dispose()
        target_engine.dispose()

    print("Transferência concluída com sucesso.")


if __name__ == "__main__":
    main()
