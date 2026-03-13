import hashlib
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import UUID

from app.infrastructure.db.models.enums import TransactionDirection

_WHITESPACE_RE = re.compile(r"\s+")
_HEADER_RE = re.compile(r"[^a-z0-9]+")

_DEBIT_HINTS = {
    "debit",
    "debito",
    "despesa",
    "expense",
    "saida",
    "outflow",
    "dr",
    "d",
}
_CREDIT_HINTS = {
    "credit",
    "credito",
    "receita",
    "income",
    "entrada",
    "inflow",
    "cr",
    "c",
}


def normalize_header(value: str | None) -> str:
    if value is None:
        return ""
    lowered = value.strip().lower()
    normalized = unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode("ascii")
    return _HEADER_RE.sub("_", normalized).strip("_")


def normalize_description(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("Descricao vazia")
    return _WHITESPACE_RE.sub(" ", trimmed)


def parse_csv_date(value: str) -> date:
    text = value.strip()
    if not text:
        raise ValueError("Data vazia")
    layouts = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y")
    for layout in layouts:
        try:
            return datetime.strptime(text, layout).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Data invalida: {value}") from exc


def parse_amount_to_cents(value: str) -> int:
    text = value.strip()
    if not text:
        raise ValueError("Valor vazio")

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()

    text = text.replace("R$", "").replace(" ", "").replace("\u00a0", "")
    sign = 1
    if text.startswith("-"):
        sign = -1
        text = text[1:]
    elif text.startswith("+"):
        text = text[1:]

    filtered = "".join(ch for ch in text if ch.isdigit() or ch in {".", ","})
    if not filtered:
        raise ValueError(f"Valor invalido: {value}")

    decimal_separator: str | None = None
    if "." in filtered and "," in filtered:
        decimal_separator = "." if filtered.rfind(".") > filtered.rfind(",") else ","
    elif "," in filtered:
        last = filtered.rsplit(",", maxsplit=1)[-1]
        if len(last) in {1, 2}:
            decimal_separator = ","
    elif "." in filtered:
        last = filtered.rsplit(".", maxsplit=1)[-1]
        if len(last) in {1, 2}:
            decimal_separator = "."

    if decimal_separator == ",":
        normalized = filtered.replace(".", "").replace(",", ".")
    elif decimal_separator == ".":
        normalized = filtered.replace(",", "")
    else:
        normalized = filtered.replace(".", "").replace(",", "")

    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"Valor invalido: {value}") from exc

    if sign < 0 or negative:
        amount = -abs(amount)
    cents = int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return cents


def infer_direction(amount_cents: int, type_hint: str | None = None) -> TransactionDirection:
    if type_hint:
        normalized = normalize_header(type_hint)
        if normalized in _DEBIT_HINTS or normalized.startswith("debit"):
            return TransactionDirection.EXPENSE
        if normalized in _CREDIT_HINTS or normalized.startswith("credit"):
            return TransactionDirection.INCOME
    if amount_cents < 0:
        return TransactionDirection.EXPENSE
    if amount_cents > 0:
        return TransactionDirection.INCOME
    raise ValueError("Valor zero nao pode definir direcao")


def build_external_transaction_hash(
    *,
    user_id: UUID,
    normalized_date: date,
    amount_cents: int,
    normalized_description: str,
    card_id: UUID | None,
    external_id: str | None = None,
) -> str:
    card_value = str(card_id) if card_id is not None else "none"
    base = (
        f"{user_id}{normalized_date.isoformat()}{amount_cents}"
        f"{normalized_description}{card_value}"
    )
    if external_id:
        base = f"{base}{external_id.strip()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def first_month_day(value: date) -> date:
    return date(value.year, value.month, 1)
