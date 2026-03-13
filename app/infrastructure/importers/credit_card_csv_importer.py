import codecs
import csv
from io import BufferedIOBase
from uuid import UUID

from app.application.dto.import_dto import (
    CSVColumnMappingDTO,
    CSVImportLineErrorDTO,
    CSVImportParseResultDTO,
    ExternalTransactionCreateDTO,
)
from app.infrastructure.importers.base import BaseCSVImporter
from app.infrastructure.importers.utils import (
    build_external_transaction_hash,
    infer_direction,
    normalize_description,
    normalize_header,
    parse_amount_to_cents,
    parse_csv_date,
)

DATE_FALLBACK_HEADERS = ("date", "data", "transaction_date", "posted_at")
DESCRIPTION_FALLBACK_HEADERS = ("description", "descricao", "historico", "memo")
AMOUNT_FALLBACK_HEADERS = ("amount", "valor", "value", "total")
EXTERNAL_ID_FALLBACK_HEADERS = ("external_id", "externalid", "id")
TYPE_FALLBACK_HEADERS = ("type", "debit_credit", "debit/credit", "tipo", "nature")


class CreditCardCSVImporter(BaseCSVImporter):
    def parse(
        self,
        *,
        stream: BufferedIOBase,
        user_id: UUID,
        import_file_id: UUID,
        card_id: UUID | None,
        mapping: CSVColumnMappingDTO | None = None,
    ) -> CSVImportParseResultDTO:
        mapping = mapping or CSVColumnMappingDTO()
        stream.seek(0)
        dialect = self._detect_dialect(stream)
        stream.seek(0)

        reader = csv.DictReader(codecs.iterdecode(stream, "utf-8-sig"), dialect=dialect)
        if not reader.fieldnames:
            raise ValueError("CSV sem cabecalho")

        field_map = {normalize_header(name): name for name in reader.fieldnames if name}
        date_column = self._resolve_required_column(field_map, mapping.date, DATE_FALLBACK_HEADERS)
        description_column = self._resolve_required_column(field_map, mapping.description, DESCRIPTION_FALLBACK_HEADERS)
        amount_column = self._resolve_required_column(field_map, mapping.amount, AMOUNT_FALLBACK_HEADERS)
        external_id_column = self._resolve_optional_column(field_map, mapping.external_id, EXTERNAL_ID_FALLBACK_HEADERS)
        type_column = self._resolve_optional_column(field_map, mapping.type, TYPE_FALLBACK_HEADERS)

        items: list[ExternalTransactionCreateDTO] = []
        errors: list[CSVImportLineErrorDTO] = []
        hashes: set[str] = set()
        duplicate_count = 0
        total_rows = 0

        for line_number, row in enumerate(reader, start=2):
            total_rows += 1
            try:
                parsed = self._parse_row(
                    row=row,
                    line_number=line_number,
                    user_id=user_id,
                    import_file_id=import_file_id,
                    card_id=card_id,
                    date_column=date_column,
                    description_column=description_column,
                    amount_column=amount_column,
                    external_id_column=external_id_column,
                    type_column=type_column,
                )
                if parsed.hash in hashes:
                    duplicate_count += 1
                    continue
                hashes.add(parsed.hash)
                items.append(parsed)
            except ValueError as exc:
                errors.append(
                    CSVImportLineErrorDTO(
                        line_number=line_number,
                        message=str(exc),
                        row_data={str(k): v for k, v in row.items() if k},
                    )
                )

        return CSVImportParseResultDTO(
            total_linhas=total_rows,
            importadas=len(items),
            duplicadas=duplicate_count,
            com_erro=len(errors),
            items=items,
            errors=errors,
        )

    @staticmethod
    def _detect_dialect(stream: BufferedIOBase) -> csv.Dialect:
        sample = stream.read(4096)
        if isinstance(sample, bytes):
            sample_text = sample.decode("utf-8-sig", errors="ignore")
        else:
            sample_text = str(sample)
        try:
            return csv.Sniffer().sniff(sample_text, delimiters=",;|\t")
        except csv.Error:
            return csv.excel

    @staticmethod
    def _resolve_required_column(
        field_map: dict[str, str],
        mapped_name: str,
        fallback_names: tuple[str, ...],
    ) -> str:
        found = CreditCardCSVImporter._resolve_optional_column(field_map, mapped_name, fallback_names)
        if found is None:
            raise ValueError(f"Coluna obrigatoria ausente: {mapped_name}")
        return found

    @staticmethod
    def _resolve_optional_column(
        field_map: dict[str, str],
        mapped_name: str | None,
        fallback_names: tuple[str, ...],
    ) -> str | None:
        candidates = [mapped_name, *fallback_names] if mapped_name else list(fallback_names)
        for candidate in candidates:
            normalized = normalize_header(candidate)
            if normalized and normalized in field_map:
                return field_map[normalized]
        return None

    @staticmethod
    def _parse_row(
        *,
        row: dict[str, str | None],
        line_number: int,
        user_id: UUID,
        import_file_id: UUID,
        card_id: UUID | None,
        date_column: str,
        description_column: str,
        amount_column: str,
        external_id_column: str | None,
        type_column: str | None,
    ) -> ExternalTransactionCreateDTO:
        raw_date_value = (row.get(date_column) or "").strip()
        raw_description_value = row.get(description_column) or ""
        raw_amount_value = (row.get(amount_column) or "").strip()
        external_id_value = (row.get(external_id_column) or "").strip() if external_id_column else None
        type_hint = (row.get(type_column) or "").strip() if type_column else None

        if not raw_date_value:
            raise ValueError(f"Linha {line_number}: data ausente")
        if not raw_description_value.strip():
            raise ValueError(f"Linha {line_number}: descricao ausente")
        if not raw_amount_value:
            raise ValueError(f"Linha {line_number}: valor ausente")

        parsed_date = parse_csv_date(raw_date_value)
        raw_amount_cents = parse_amount_to_cents(raw_amount_value)
        normalized_desc = normalize_description(raw_description_value)
        direction = infer_direction(raw_amount_cents, type_hint)
        hash_value = build_external_transaction_hash(
            user_id=user_id,
            normalized_date=parsed_date,
            amount_cents=raw_amount_cents,
            normalized_description=normalized_desc,
            card_id=card_id,
            external_id=external_id_value,
        )

        return ExternalTransactionCreateDTO(
            user_id=user_id,
            import_file_id=import_file_id,
            source="csv",
            card_id=card_id,
            raw_date=parsed_date,
            raw_description=raw_description_value,
            raw_amount_cents=raw_amount_cents,
            normalized_date=parsed_date,
            normalized_description=normalized_desc,
            amount_cents=raw_amount_cents,
            direction=direction,
            external_id=external_id_value or None,
            hash=hash_value,
            raw_row_json={str(k): v for k, v in row.items() if k is not None},
        )
