from datetime import date
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.application.dto.business_control_dto import (
    CreateBusinessDTO,
    CreateBusinessFundingDTO,
    CreateMemberDTO,
    CreateSubscriptionDTO,
    PayBusinessFundingInstallmentDTO,
    RecordReceiptDTO,
)
from app.application.use_cases.business_control_finance import BusinessControlFinanceService
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import (
    audit_log,
    business,
    business_account,
    business_cash_entry,
    business_category,
    business_funding,
    business_funding_installment,
    cost_center,
    member,
    membership_plan,
    receipt,
    receivable,
    subscription,
    user,
)
from app.infrastructure.db.models.business_cash_entry import BusinessCashEntry
from app.infrastructure.db.models.business_category import BusinessCategory
from app.infrastructure.db.models.business_funding_installment import BusinessFundingInstallment
from app.infrastructure.db.models.enums import (
    BusinessCashActivityType,
    MemberStatus,
    ReceiptMethod,
    TransactionDirection,
)
from app.infrastructure.db.models.receivable import Receivable
from app.infrastructure.db.models.user import User

_ = (
    audit_log,
    business,
    business_account,
    business_cash_entry,
    business_category,
    business_funding,
    business_funding_installment,
    cost_center,
    member,
    membership_plan,
    receipt,
    receivable,
    subscription,
    user,
)


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _seed_business(service: BusinessControlFinanceService, owner: User):
    return service.create_business(
        actor_user_id=owner.id,
        payload=CreateBusinessDTO(
            name="Soomei",
            slug=f"soomei-{owner.id.hex[:8]}",
            seed_template="SOOMEI",
        ),
    )


def test_create_funding_generates_cash_inflow_and_installments() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="funding@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = BusinessControlFinanceService(db)
        created_business = _seed_business(service, owner)
        account = service.list_accounts(owner_user_id=owner.id, business_id=created_business.id)[0]
        fin_category = db.scalar(
            select(BusinessCategory).where(
                BusinessCategory.business_id == created_business.id,
                BusinessCategory.code == "FIN",
            )
        )

        funding = service.create_funding(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=CreateBusinessFundingDTO(
                name="Credito inicial",
                lender_name="Banco Teste",
                disbursement_account_id=account.id,
                settlement_account_id=account.id,
                payment_category_id=fin_category.id if fin_category is not None else None,
                cost_center_id=None,
                principal_cents=100_000_00,
                installment_amount_cents=3_125_00,
                installment_count=36,
                annual_interest_bps=1_250,
                disbursed_on=date(2026, 3, 13),
                first_due_on=date(2026, 3, 20),
                notes="Capital inicial",
            ),
        )

        installments = service.list_funding_installments(owner_user_id=owner.id, business_id=created_business.id)
        inflow = db.scalar(
            select(BusinessCashEntry).where(
                BusinessCashEntry.funding_id == funding.id,
                BusinessCashEntry.direction == TransactionDirection.INCOME,
            )
        )

        assert funding.principal_cents == 100_000_00
        assert len(installments) == 36
        assert inflow is not None
        assert inflow.activity_type == BusinessCashActivityType.FINANCING
        assert inflow.amount_cents == 100_000_00
    finally:
        db.close()


def test_pay_installment_updates_schedule_and_cash_flow() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="installment@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = BusinessControlFinanceService(db)
        created_business = _seed_business(service, owner)
        account = service.list_accounts(owner_user_id=owner.id, business_id=created_business.id)[0]

        service.create_funding(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=CreateBusinessFundingDTO(
                name="Credito ponte",
                lender_name="Banco Teste",
                disbursement_account_id=account.id,
                settlement_account_id=account.id,
                payment_category_id=None,
                cost_center_id=None,
                principal_cents=20_000_00,
                installment_amount_cents=2_200_00,
                installment_count=10,
                annual_interest_bps=1_000,
                disbursed_on=date(2026, 3, 13),
                first_due_on=date(2026, 3, 18),
                notes=None,
            ),
        )
        installment = service.list_funding_installments(
            owner_user_id=owner.id,
            business_id=created_business.id,
            limit=1,
        )[0]

        paid = service.pay_funding_installment(
            actor_user_id=owner.id,
            business_id=created_business.id,
            installment_id=installment.id,
            payload=PayBusinessFundingInstallmentDTO(
                paid_on=date(2026, 3, 18),
                amount_paid_cents=2_200_00,
                notes="Primeira parcela quitada.",
            ),
        )
        payment_entry = db.get(BusinessCashEntry, paid.payment_entry_id)
        dashboard = service.build_dashboard(owner_user_id=owner.id, business_id=created_business.id)

        assert paid.status.value == "PAID"
        assert payment_entry is not None
        assert payment_entry.direction == TransactionDirection.EXPENSE
        assert payment_entry.amount_cents == 2_200_00
        assert dashboard.current_cash_cents == 17_800_00
    finally:
        db.close()


def test_record_receipt_creates_operating_cash_entry() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="cashreceipt@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = BusinessControlFinanceService(db)
        created_business = _seed_business(service, owner)
        member_row = service.create_member(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=CreateMemberDTO(
                full_name="Associado Caixa",
                email="caixa@teste.local",
                status=MemberStatus.ACTIVE,
                joined_on=date.today(),
            ),
        )
        plan = service.list_membership_plans(owner_user_id=owner.id, business_id=created_business.id)[0]
        subscription_row = service.create_subscription(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=CreateSubscriptionDTO(
                member_id=member_row.id,
                membership_plan_id=plan.id,
                started_on=date.today(),
                first_due_on=date.today(),
                price_override_cents=None,
                notes=None,
            ),
        )
        receivable_row = db.scalar(
            select(Receivable).where(
                Receivable.subscription_id == subscription_row.id,
                Receivable.amount_cents == plan.recurring_amount_cents,
            )
        )
        assert receivable_row is not None

        service.record_receipt(
            actor_user_id=owner.id,
            business_id=created_business.id,
            receivable_id=receivable_row.id,
            payload=RecordReceiptDTO(
                received_on=date.today(),
                amount_received_cents=plan.recurring_amount_cents,
                method=ReceiptMethod.PIX,
                note="Recebimento de teste.",
            ),
        )

        cash_entries = service.list_cash_entries(owner_user_id=owner.id, business_id=created_business.id)
        receipt_entry = next(
            item for item in cash_entries if item.description.startswith("Recebimento:")
        )
        dashboard = service.build_dashboard(owner_user_id=owner.id, business_id=created_business.id)

        assert receipt_entry.direction == TransactionDirection.INCOME
        assert receipt_entry.activity_type == BusinessCashActivityType.OPERATING
        assert receipt_entry.amount_cents == plan.recurring_amount_cents
        assert dashboard.inflows_this_month_cents >= plan.recurring_amount_cents
        assert dashboard.current_cash_cents >= plan.recurring_amount_cents
    finally:
        db.close()


def test_themembers_one_time_sale_updates_cash_and_daily_growth() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="growth@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = BusinessControlFinanceService(db)
        created_business = _seed_business(service, owner)
        integration = service.create_checkout_integration(actor_user_id=owner.id, business_id=created_business.id)
        today_iso = date.today().isoformat()
        payload = {
            "payload": {
                "id": "evt-growth-001",
                "event": "transaction.approved",
                "data": {
                    "customer": {
                        "id": "cust-growth-001",
                        "name": "Compradora Crescimento",
                        "email": "growth-course@test.local",
                    },
                    "main_product": {
                        "id": "curso-soomei",
                        "reference_id": "TM-CURSO-SOOMEI",
                        "title": "Curso Receita Recorrente",
                    },
                    "transaction": {
                        "id": "TRX-GROWTH-001",
                        "value": 2990,
                        "method": "pix",
                        "paid_at": f"{today_iso}T10:05:00Z",
                    },
                    "order": {
                        "id": "ORD-GROWTH-001",
                        "total": 2990,
                        "created_at": f"{today_iso}T10:00:00Z",
                    },
                },
            }
        }

        service.handle_checkout_webhook(
            webhook_path_token=integration.integration.webhook_path_token,
            signature=integration.webhook_secret or "",
            body=payload,
            request_id="req-growth",
            source_ip="127.0.0.1",
            user_agent="pytest",
        )

        cash_entries = service.list_cash_entries(owner_user_id=owner.id, business_id=created_business.id)
        dashboard = service.build_dashboard(owner_user_id=owner.id, business_id=created_business.id)
        receipt_entry = next(item for item in cash_entries if item.description.startswith("Recebimento: Produto TheMembers"))

        assert receipt_entry.direction == TransactionDirection.INCOME
        assert receipt_entry.amount_cents == 2990
        assert dashboard.one_time_sales_this_month_cents == 2990
        assert dashboard.revenue_today_cents == 2990
        assert dashboard.new_members_today == 1
        assert dashboard.daily_growth_points[-1].paid_orders_count == 1
    finally:
        db.close()
