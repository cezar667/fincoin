from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import engine_from_config, inspect, pool, text

from app.infrastructure.db.base import Base
from app.infrastructure.settings.config import get_settings
from app.infrastructure.db import models as _models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata
script = ScriptDirectory.from_config(config)

_REVISION_MARKERS: list[tuple[str, set[str]]] = [
    ("20260313_0007", {"business_cash_entries", "business_fundings", "business_funding_installments"}),
    ("20260313_0006", {"business_integrations", "webhook_events"}),
    ("20260313_0005", {"members", "membership_plans", "subscriptions", "receivables", "receipts"}),
    ("20260313_0004", {"businesses", "business_accounts", "business_categories", "cost_centers", "audit_logs"}),
    ("20260221_0002", {"import_files", "external_transactions"}),
    (
        "20260216_0001",
        {
            "users",
            "accounts",
            "categories",
            "transactions",
            "recurring_rules",
            "credit_cards",
            "installments",
            "debts",
            "debt_plans",
            "notifications",
        },
    ),
]


def _schema_supports_0007(inspector) -> bool:
    tables = set(inspector.get_table_names())
    if not {"business_cash_entries", "business_fundings", "business_funding_installments"}.issubset(tables):
        return False
    cash_columns = {item["name"] for item in inspector.get_columns("business_cash_entries")}
    installment_columns = {item["name"] for item in inspector.get_columns("business_funding_installments")}
    return "funding_id" in cash_columns and "payment_entry_id" in installment_columns


def _schema_supports_0006(inspector) -> bool:
    tables = set(inspector.get_table_names())
    if not {"business_integrations", "webhook_events"}.issubset(tables):
        return False
    membership_plan_columns = {item["name"] for item in inspector.get_columns("membership_plans")}
    receipt_columns = {item["name"] for item in inspector.get_columns("receipts")}
    return "external_product_id" in membership_plan_columns and "external_transaction_id" in receipt_columns


def _infer_existing_revision(connection) -> str | None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if _schema_supports_0007(inspector):
        return "20260313_0007"
    if _schema_supports_0006(inspector):
        return "20260313_0006"
    if "alembic_version" in tables:
        version_rows = connection.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        if version_rows:
            return str(version_rows[0][0])

    metadata_tables = {table.name for table in target_metadata.sorted_tables}
    if metadata_tables.issubset(tables):
        return script.get_current_head()

    account_columns = set()
    if "accounts" in tables:
        account_columns = {item["name"] for item in inspector.get_columns("accounts")}
    if "initial_balance_cents" in account_columns:
        return "20260311_0003"

    for revision_id, marker_tables in _REVISION_MARKERS:
        if marker_tables.issubset(tables):
            return revision_id
    return None


def _ensure_legacy_schema_version(connection) -> None:
    inferred_revision = _infer_existing_revision(connection)
    if inferred_revision is None:
        return

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "alembic_version" not in tables:
        connection.execute(
            text(
                "CREATE TABLE alembic_version ("
                "version_num VARCHAR(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )

    version_rows = connection.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    if version_rows:
        if str(version_rows[0][0]) != inferred_revision:
            connection.execute(
                text("UPDATE alembic_version SET version_num = :revision_id"),
                {"revision_id": inferred_revision},
            )
            connection.commit()
        return
    connection.execute(
        text("INSERT INTO alembic_version (version_num) VALUES (:revision_id)"),
        {"revision_id": inferred_revision},
    )
    connection.commit()


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        _ensure_legacy_schema_version(connection)
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
