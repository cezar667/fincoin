"""One-time, guarded transfer of a FinSight SQLite database to PostgreSQL."""

import argparse
import uuid
from collections.abc import Iterator

from sqlalchemy import MetaData, Table, create_engine, func, select
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


def _normalized_key(values: tuple[object, ...]) -> tuple[str, ...]:
    """Compare SQLite and PostgreSQL identifiers consistently (UUIDs differ in type)."""
    normalized: list[str] = []
    for value in values:
        try:
            normalized.append(str(uuid.UUID(str(value))))
        except (AttributeError, TypeError, ValueError):
            normalized.append(str(value))
    return tuple(normalized)


def _foreign_key_values(
    connection: Connection,
    table: Table,
    cache: dict[tuple[str, tuple[str, ...]], set[tuple[str, ...]]],
) -> list[tuple[tuple[str, ...], set[tuple[str, ...]], str]]:
    result: list[tuple[tuple[str, ...], set[tuple[str, ...]], str]] = []
    for constraint in table.foreign_key_constraints:
        local_columns = tuple(element.parent.name for element in constraint.elements)
        parent_table = constraint.referred_table
        parent_columns = tuple(element.column.name for element in constraint.elements)
        cache_key = (parent_table.name, parent_columns)
        if cache_key not in cache:
            rows = connection.execute(
                select(*(parent_table.c[column] for column in parent_columns))
            ).all()
            cache[cache_key] = {_normalized_key(tuple(row)) for row in rows}
        result.append((local_columns, cache[cache_key], parent_table.name))
    return result


def _clear_target(connection: Connection) -> None:
    """Delete only FinSight tables, from children to parents, in one transaction."""
    for table in reversed(Base.metadata.sorted_tables):
        connection.execute(table.delete())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transfere uma base SQLite FinSight para um PostgreSQL vazio."
    )
    parser.add_argument(
        "--source-url",
        required=True,
        help="URL SQLAlchemy do SQLite de origem, por exemplo sqlite+pysqlite:////transfer/finsight.db",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help=(
            "Remove os dados atuais das tabelas do FinSight antes da transferência. "
            "Use somente para refazer uma importação incompleta."
        ),
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
                if not args.replace_existing:
                    parser.error(
                        "O PostgreSQL de destino já tem dados. "
                        "A transferência foi interrompida para não misturar informações."
                    )
                _clear_target(target_connection)
                print(
                    "Dados anteriores do FinSight removidos para refazer a transferência."
                )
            foreign_key_cache: dict[
                tuple[str, tuple[str, ...]], set[tuple[str, ...]]
            ] = {}
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
                    parent_keys = _foreign_key_values(
                        target_connection, target_table, foreign_key_cache
                    )
                    row_count = 0
                    skipped_count = 0
                    remapped_user_count = 0

                    def valid_rows(
                        rows_result=result,
                        rows_parent_keys=parent_keys,
                    ) -> Iterator[dict[str, object]]:
                        nonlocal remapped_user_count, skipped_count
                        for source_row in rows_result.mappings():
                            row = dict(source_row)
                            valid = True
                            for (
                                local_columns,
                                valid_parent_keys,
                                parent_table_name,
                            ) in rows_parent_keys:
                                values = tuple(
                                    row.get(column) for column in local_columns
                                )
                                if any(value is None for value in values):
                                    continue
                                if _normalized_key(values) not in valid_parent_keys:
                                    if (
                                        parent_table_name == "users"
                                        and len(valid_parent_keys) == 1
                                        and len(local_columns) == 1
                                    ):
                                        row[local_columns[0]] = next(
                                            iter(valid_parent_keys)
                                        )[0]
                                        remapped_user_count += 1
                                        continue
                                    valid = False
                                    break
                            if valid:
                                yield row
                            else:
                                skipped_count += 1

                    rows = valid_rows()
                    for batch in _batches(rows):
                        target_connection.execute(target_table.insert(), batch)
                        row_count += len(batch)
                message = f"{target_table.name}: {row_count} registros transferidos"
                if skipped_count:
                    message += f"; {skipped_count} ignorados por referência inexistente"
                if remapped_user_count:
                    message += (
                        f"; {remapped_user_count} associados ao usuário recuperado"
                    )
                print(message)
    finally:
        source_engine.dispose()
        target_engine.dispose()

    print("Transferência concluída com sucesso.")


if __name__ == "__main__":
    main()
