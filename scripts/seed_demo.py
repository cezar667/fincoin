from datetime import date

from app.application.dto.business_control_dto import (
    CreateBusinessCashEntryDTO,
    CreateBusinessDTO,
    CreateBusinessFundingDTO,
    CreateMemberDTO,
    CreateSubscriptionDTO,
    UpsertMembershipPlanDTO,
)
from app.application.use_cases.business_control_finance import BusinessControlFinanceService
from app.infrastructure.auth.password import hash_password
from app.infrastructure.db.base import Base
from app.infrastructure.db.legacy import ensure_sqlite_legacy_business_control_schema
from app.infrastructure.db.models.account import Account
from app.infrastructure.db.models.category import Category
from app.infrastructure.db.models.business import Business
from app.infrastructure.db.models.business_category import BusinessCategory
from app.infrastructure.db.models.cost_center import CostCenter
from app.infrastructure.db.models.enums import (
    AccountType,
    BusinessCashActivityType,
    CategoryKind,
    MemberStatus,
    TransactionDirection,
)
from app.infrastructure.db.models.member import Member
from app.infrastructure.db.models.membership_plan import MembershipPlan
from app.infrastructure.db.models.subscription import Subscription
from app.infrastructure.db.models.user import User
from app.infrastructure.db.session import SessionLocal, engine


def _ensure_demo_business(db, user: User) -> None:
    service = BusinessControlFinanceService(db)
    plan_mapping = {
        "Soomei Start": {"external_product_id": "soomei-start", "external_reference_id": "TM-SOOMEI-START"},
        "Soomei Prime": {"external_product_id": "soomei-prime", "external_reference_id": "TM-SOOMEI-PRIME"},
    }
    existing_business = db.query(Business).filter(Business.owner_user_id == user.id, Business.slug == "soomei").first()
    if existing_business is None:
        existing_business = service.create_business(
            actor_user_id=user.id,
            payload=CreateBusinessDTO(
                name="Soomei",
                slug="soomei",
                legal_name="Soomei Demo Ltda",
                description="Business seed para recorrencia, cartoes e operacao empresarial.",
                seed_template="SOOMEI",
            ),
        )
    else:
        service._ensure_soomei_membership_plans(
            actor_user_id=user.id,
            business_id=existing_business.id,
            request_id=None,
        )
        for current_plan in service.list_membership_plans(owner_user_id=user.id, business_id=existing_business.id):
            mapping = plan_mapping.get(current_plan.name)
            if mapping is None:
                continue
            if (
                current_plan.external_product_id == mapping["external_product_id"]
                and current_plan.external_reference_id == mapping["external_reference_id"]
            ):
                continue
            service.update_membership_plan(
                actor_user_id=user.id,
                business_id=existing_business.id,
                plan_id=current_plan.id,
                payload=UpsertMembershipPlanDTO(
                    name=current_plan.name,
                    description=current_plan.description,
                    external_product_id=mapping["external_product_id"],
                    external_reference_id=mapping["external_reference_id"],
                    cadence=current_plan.cadence,
                    recurring_amount_cents=current_plan.recurring_amount_cents,
                    activation_fee_cents=current_plan.activation_fee_cents,
                    billing_day=current_plan.billing_day,
                    grace_days=current_plan.grace_days,
                ),
            )

    today = date.today()
    demo_member = (
        db.query(Member)
        .filter(Member.business_id == existing_business.id, Member.full_name == "Associado Demo")
        .first()
    )
    if demo_member is None:
        demo_member = service.create_member(
            actor_user_id=user.id,
            business_id=existing_business.id,
            payload=CreateMemberDTO(
                full_name="Associado Demo",
                email="associado.demo@soomei.local",
                phone="(11) 90000-0000",
                document_number="000.000.000-00",
                status=MemberStatus.ACTIVE,
                joined_on=today,
                notes="Cliente seed para validar jornada e cobranca recorrente.",
            ),
        )

    first_plan = (
        db.query(MembershipPlan)
        .filter(MembershipPlan.business_id == existing_business.id, MembershipPlan.is_active.is_(True))
        .order_by(MembershipPlan.created_at.asc())
        .first()
    )
    existing_subscription = (
        db.query(Subscription)
        .filter(
            Subscription.business_id == existing_business.id,
            Subscription.member_id == demo_member.id,
        )
        .first()
    )
    if first_plan is not None and existing_subscription is None:
        service.create_subscription(
            actor_user_id=user.id,
            business_id=existing_business.id,
            payload=CreateSubscriptionDTO(
                member_id=demo_member.id,
                membership_plan_id=first_plan.id,
                started_on=today,
                first_due_on=today,
                price_override_cents=None,
                notes="Assinatura demo inicial.",
            ),
        )

    categories = {
        item.code: item
        for item in db.query(BusinessCategory).filter(BusinessCategory.business_id == existing_business.id).all()
        if item.code
    }
    cost_centers = {
        item.code: item
        for item in db.query(CostCenter).filter(CostCenter.business_id == existing_business.id).all()
        if item.code
    }
    accounts = service.list_accounts(owner_user_id=user.id, business_id=existing_business.id)
    operational_account = next((item for item in accounts if item.name == "Conta Operacional"), accounts[0])
    funding_rows = service.list_fundings(owner_user_id=user.id, business_id=existing_business.id)
    credit_name = "Credito inicial Soomei"
    funding_row = next((item for item in funding_rows if item.name == credit_name), None)
    if funding_row is None:
        funding_row = service.create_funding(
            actor_user_id=user.id,
            business_id=existing_business.id,
            payload=CreateBusinessFundingDTO(
                name=credit_name,
                lender_name="Credito consignado demo",
                disbursement_account_id=operational_account.id,
                settlement_account_id=operational_account.id,
                payment_category_id=categories.get("FIN").id if categories.get("FIN") else None,
                cost_center_id=cost_centers.get("ADM").id if cost_centers.get("ADM") else None,
                principal_cents=100_000_00,
                installment_amount_cents=3_125_00,
                installment_count=36,
                annual_interest_bps=12_50,
                disbursed_on=today,
                first_due_on=today,
                notes="Capital inicial de demonstracao para investimento na Soomei.",
            ),
        )

    existing_descriptions = {
        item.description
        for item in service.list_cash_entries(owner_user_id=user.id, business_id=existing_business.id, limit=200)
    }
    demo_entries = [
        {
            "description": "Landing page e checkout de aquisicao",
            "amount_cents": 12_500_00,
            "category_id": categories.get("INV").id if categories.get("INV") else None,
            "cost_center_id": cost_centers.get("TECH").id if cost_centers.get("TECH") else None,
            "activity_type": BusinessCashActivityType.INVESTING,
            "occurred_on": today,
        },
        {
            "description": "Trafego pago de lancamento",
            "amount_cents": 8_000_00,
            "category_id": categories.get("INV").id if categories.get("INV") else None,
            "cost_center_id": cost_centers.get("COM").id if cost_centers.get("COM") else None,
            "activity_type": BusinessCashActivityType.INVESTING,
            "occurred_on": today,
        },
        {
            "description": "Emissao inicial de cartoes NFC",
            "amount_cents": 3_500_00,
            "category_id": categories.get("CARD").id if categories.get("CARD") else None,
            "cost_center_id": cost_centers.get("OPER").id if cost_centers.get("OPER") else None,
            "activity_type": BusinessCashActivityType.OPERATING,
            "occurred_on": today,
        },
    ]
    for item in demo_entries:
        if item["description"] in existing_descriptions:
            continue
        service.create_cash_entry(
            actor_user_id=user.id,
            business_id=existing_business.id,
            payload=CreateBusinessCashEntryDTO(
                business_account_id=operational_account.id,
                business_category_id=item["category_id"],
                cost_center_id=item["cost_center_id"],
                funding_id=funding_row.id,
                activity_type=item["activity_type"],
                direction=TransactionDirection.EXPENSE,
                description=item["description"],
                amount_cents=item["amount_cents"],
                occurred_on=item["occurred_on"],
                notes="Saida seed para demonstrar onde o credito esta sendo consumido.",
            ),
        )


def run() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_legacy_business_control_schema(engine)
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == "demo@finsight.local").first()
        if existing is not None:
            existing.password_hash = hash_password("demo123")
            existing.is_active = True
            db.add(existing)
            db.commit()
            _ensure_demo_business(db, existing)
            return
        user = User(email="demo@finsight.local", password_hash=hash_password("demo123"), is_active=True)
        db.add(user)
        db.flush()
        db.add(Account(user_id=user.id, name="Conta Principal", type=AccountType.BANK))
        db.add(Category(user_id=user.id, name="Salario", kind=CategoryKind.INCOME))
        db.add(Category(user_id=user.id, name="Moradia", kind=CategoryKind.EXPENSE))
        _ensure_demo_business(db, user)
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    run()
