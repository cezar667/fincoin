from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def ensure_sqlite_legacy_business_control_schema(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    required_tables = {"members", "membership_plans", "subscriptions", "receivables", "receipts"}
    if not required_tables.issubset(tables):
        return

    statements: list[str] = []
    temp_tables = [name for name in tables if name.startswith("_alembic_tmp_")]
    statements.extend(f'DROP TABLE IF EXISTS "{name}"' for name in temp_tables)

    member_columns = {item["name"] for item in inspector.get_columns("members")}
    if "external_customer_id" not in member_columns:
        statements.append("ALTER TABLE members ADD COLUMN external_customer_id VARCHAR(120)")
    member_indexes = {item["name"] for item in inspector.get_indexes("members")}
    if "uq_members_business_external_customer" not in member_indexes:
        statements.append(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_members_business_external_customer "
            "ON members (business_id, external_customer_id)"
        )

    plan_columns = {item["name"] for item in inspector.get_columns("membership_plans")}
    if "external_product_id" not in plan_columns:
        statements.append("ALTER TABLE membership_plans ADD COLUMN external_product_id VARCHAR(120)")
    if "external_reference_id" not in plan_columns:
        statements.append("ALTER TABLE membership_plans ADD COLUMN external_reference_id VARCHAR(120)")
    plan_indexes = {item["name"] for item in inspector.get_indexes("membership_plans")}
    if "uq_membership_plans_business_external_product" not in plan_indexes:
        statements.append(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_membership_plans_business_external_product "
            "ON membership_plans (business_id, external_product_id)"
        )
    if "uq_membership_plans_business_external_reference" not in plan_indexes:
        statements.append(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_membership_plans_business_external_reference "
            "ON membership_plans (business_id, external_reference_id)"
        )

    subscription_columns = {item["name"] for item in inspector.get_columns("subscriptions")}
    if "external_subscription_id" not in subscription_columns:
        statements.append("ALTER TABLE subscriptions ADD COLUMN external_subscription_id VARCHAR(120)")
    if "cancel_requested_at" not in subscription_columns:
        statements.append("ALTER TABLE subscriptions ADD COLUMN cancel_requested_at DATETIME")
    subscription_indexes = {item["name"] for item in inspector.get_indexes("subscriptions")}
    if "uq_subscriptions_business_external_subscription" not in subscription_indexes:
        statements.append(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_subscriptions_business_external_subscription "
            "ON subscriptions (business_id, external_subscription_id)"
        )

    receivable_columns = {item["name"] for item in inspector.get_columns("receivables")}
    if "external_invoice_id" not in receivable_columns:
        statements.append("ALTER TABLE receivables ADD COLUMN external_invoice_id VARCHAR(120)")
    if "external_order_id" not in receivable_columns:
        statements.append("ALTER TABLE receivables ADD COLUMN external_order_id VARCHAR(120)")
    receivable_indexes = {item["name"] for item in inspector.get_indexes("receivables")}
    if "uq_receivables_business_external_invoice" not in receivable_indexes:
        statements.append(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_receivables_business_external_invoice "
            "ON receivables (business_id, external_invoice_id)"
        )
    if "ix_receivables_business_external_order" not in receivable_indexes:
        statements.append(
            "CREATE INDEX IF NOT EXISTS ix_receivables_business_external_order "
            "ON receivables (business_id, external_order_id)"
        )

    receipt_columns = {item["name"] for item in inspector.get_columns("receipts")}
    if "external_transaction_id" not in receipt_columns:
        statements.append("ALTER TABLE receipts ADD COLUMN external_transaction_id VARCHAR(120)")
    receipt_indexes = {item["name"] for item in inspector.get_indexes("receipts")}
    if "uq_receipts_business_external_transaction" not in receipt_indexes:
        statements.append(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_receipts_business_external_transaction "
            "ON receipts (business_id, external_transaction_id)"
        )

    if not statements:
        _maybe_advance_alembic_version(engine)
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    _maybe_advance_alembic_version(engine)


def _maybe_advance_alembic_version(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "alembic_version" not in tables:
        return
    membership_plan_columns = {item["name"] for item in inspector.get_columns("membership_plans")}
    receipt_columns = {item["name"] for item in inspector.get_columns("receipts")}
    if "external_product_id" not in membership_plan_columns or "external_transaction_id" not in receipt_columns:
        return
    with engine.begin() as connection:
        version_rows = connection.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        if not version_rows:
            return
        if str(version_rows[0][0]) == "20260313_0005":
            connection.execute(
                text("UPDATE alembic_version SET version_num = '20260313_0006' WHERE version_num = '20260313_0005'")
            )
