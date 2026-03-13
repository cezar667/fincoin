from datetime import date
from uuid import UUID

from app.infrastructure.importers.utils import build_external_transaction_hash, parse_amount_to_cents


def test_parse_amount_to_cents_supports_ptbr_and_en() -> None:
    assert parse_amount_to_cents("1.234,56") == 123_456
    assert parse_amount_to_cents("1234.56") == 123_456
    assert parse_amount_to_cents("-123,45") == -12_345


def test_external_hash_uses_external_id_when_available() -> None:
    user_id = UUID("11111111-1111-1111-1111-111111111111")
    card_id = UUID("22222222-2222-2222-2222-222222222222")

    hash_without_external = build_external_transaction_hash(
        user_id=user_id,
        normalized_date=date(2026, 2, 1),
        amount_cents=-12_345,
        normalized_description="Mercado Central",
        card_id=card_id,
        external_id=None,
    )
    hash_with_external = build_external_transaction_hash(
        user_id=user_id,
        normalized_date=date(2026, 2, 1),
        amount_cents=-12_345,
        normalized_description="Mercado Central",
        card_id=card_id,
        external_id="abc-123",
    )

    assert hash_without_external != hash_with_external
