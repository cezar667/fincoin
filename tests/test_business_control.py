from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from datetime import date

from app.application.dto.business_control_dto import (
    CreateBusinessDTO,
    CreateMemberDTO,
    CreateSubscriptionDTO,
    RecordReceiptDTO,
    UpsertBusinessAccountDTO,
    UpsertMembershipPlanDTO,
)
from app.application.use_cases.business_control import (
    SOOMEI_ACCOUNTS,
    SOOMEI_CATEGORIES,
    SOOMEI_COST_CENTERS,
    BusinessControlService,
)
from app.application.use_cases.business_control_phase2 import BusinessControlWorkspaceService
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import (
    audit_log,
    business,
    business_account,
    business_category,
    cost_center,
    member,
    membership_plan,
    receipt,
    receivable,
    subscription,
    user,
)
from app.infrastructure.db.models.audit_log import AuditLog
from app.infrastructure.db.models.business import Business
from app.infrastructure.db.models.business_account import BusinessAccount
from app.infrastructure.db.models.cost_center import CostCenter
from app.infrastructure.db.models.enums import (
    BillingCadence,
    BusinessAccountType,
    MemberStatus,
    ReceiptMethod,
    SubscriptionStatus,
)
from app.infrastructure.db.models.receivable import Receivable
from app.infrastructure.db.models.subscription import Subscription
from app.infrastructure.db.models.user import User

_ = (
    audit_log,
    business,
    business_account,
    business_category,
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


def test_create_business_with_soomei_seed_creates_foundation_and_audits() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="owner@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = BusinessControlService(db)
        created = service.create_business(
            actor_user_id=owner.id,
            payload=CreateBusinessDTO(
                name="Soomei",
                slug="Soomei Oficial",
                legal_name="Soomei Tecnologia Ltda",
                description="Operacao com recorrencia e cartoes.",
                seed_template="SOOMEI",
            ),
            request_id="req-1",
        )

        assert created.slug == "soomei-oficial"
        assert db.scalar(select(Business).where(Business.owner_user_id == owner.id)) is not None
        assert len(list(db.scalars(select(BusinessAccount).where(BusinessAccount.business_id == created.id)))) == len(
            SOOMEI_ACCOUNTS
        )
        assert len(list(db.scalars(select(CostCenter).where(CostCenter.business_id == created.id)))) == len(
            SOOMEI_COST_CENTERS
        )
        assert len(
            list(
                db.scalars(
                    select(AuditLog).where(
                        AuditLog.business_id == created.id,
                    )
                )
            )
        ) == 2

        dashboard = service.build_dashboard(owner_user_id=owner.id, business_id=created.id)
        assert dashboard.active_accounts == len(SOOMEI_ACCOUNTS)
        assert dashboard.active_categories == len(SOOMEI_CATEGORIES)
        assert dashboard.active_cost_centers == len(SOOMEI_COST_CENTERS)
        assert dashboard.active_businesses == 1
    finally:
        db.close()


def test_business_account_names_must_be_unique_per_business() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="duplicate@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = BusinessControlService(db)
        created = service.create_business(
            actor_user_id=owner.id,
            payload=CreateBusinessDTO(name="Empresa", slug="empresa"),
        )
        service.create_account(
            actor_user_id=owner.id,
            business_id=created.id,
            payload=UpsertBusinessAccountDTO(
                name="Conta Caixa",
                type=BusinessAccountType.CASH,
                initial_balance_cents=10_000,
            ),
        )

        with pytest.raises(ValueError, match="Ja existe uma conta empresarial com este nome."):
            service.create_account(
                actor_user_id=owner.id,
                business_id=created.id,
                payload=UpsertBusinessAccountDTO(
                    name="conta caixa",
                    type=BusinessAccountType.BANK,
                    initial_balance_cents=0,
                ),
            )
    finally:
        db.close()


def test_business_isolation_rejects_foreign_user_access() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="owner2@test.local", password_hash="hash")
        outsider = User(id=uuid4(), email="outsider@test.local", password_hash="hash")
        db.add_all([owner, outsider])
        db.commit()

        service = BusinessControlService(db)
        created = service.create_business(
            actor_user_id=owner.id,
            payload=CreateBusinessDTO(name="Empresa A", slug="empresa-a"),
        )

        with pytest.raises(ValueError, match="Business nao encontrado."):
            service.get_business(owner_user_id=outsider.id, business_id=created.id)
    finally:
        db.close()


def test_create_subscription_generates_initial_receivables() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="phase2@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = BusinessControlWorkspaceService(db)
        created_business = service.create_business(
            actor_user_id=owner.id,
            payload=CreateBusinessDTO(name="Soomei", slug="soomei-phase2"),
        )
        created_member = service.create_member(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=CreateMemberDTO(
                full_name="Associado Teste",
                email="membro@test.local",
                status=MemberStatus.LEAD,
                joined_on=date(2026, 3, 1),
            ),
        )
        created_plan = service.create_membership_plan(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=UpsertMembershipPlanDTO(
                name="Plano Essencial",
                description="Teste",
                cadence=BillingCadence.MONTHLY,
                recurring_amount_cents=59_90,
                activation_fee_cents=19_90,
                billing_day=5,
                grace_days=2,
            ),
        )

        created_subscription = service.create_subscription(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=CreateSubscriptionDTO(
                member_id=created_member.id,
                membership_plan_id=created_plan.id,
                started_on=date(2026, 3, 2),
                first_due_on=date(2026, 3, 5),
                price_override_cents=None,
                notes="Teste inicial",
            ),
        )

        receivables = list(
            db.scalars(
                select(Receivable).where(Receivable.subscription_id == created_subscription.id)
            )
        )
        assert len(receivables) == 2
        assert created_subscription.next_billing_on == date(2026, 4, 5)
        refreshed_member = service._get_member(business_id=created_business.id, member_id=created_member.id)
        assert refreshed_member.status == MemberStatus.ACTIVE
    finally:
        db.close()


def test_record_receipt_marks_receivable_paid_when_balance_is_cleared() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="receipt@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = BusinessControlWorkspaceService(db)
        created_business = service.create_business(
            actor_user_id=owner.id,
            payload=CreateBusinessDTO(name="Empresa Receb", slug="empresa-receb"),
        )
        created_member = service.create_member(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=CreateMemberDTO(
                full_name="Cliente Recebimento",
                status=MemberStatus.ACTIVE,
                joined_on=date(2026, 3, 1),
            ),
        )
        created_plan = service.create_membership_plan(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=UpsertMembershipPlanDTO(
                name="Plano Receb",
                cadence=BillingCadence.MONTHLY,
                recurring_amount_cents=100_00,
                activation_fee_cents=0,
                billing_day=10,
                grace_days=0,
            ),
        )
        subscription_row = service.create_subscription(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=CreateSubscriptionDTO(
                member_id=created_member.id,
                membership_plan_id=created_plan.id,
                started_on=date(2026, 3, 1),
                first_due_on=date(2026, 3, 10),
                price_override_cents=None,
                notes=None,
            ),
        )
        receivable_row = db.scalar(
            select(Receivable).where(
                Receivable.subscription_id == subscription_row.id,
                Receivable.amount_cents == 100_00,
            )
        )
        assert receivable_row is not None

        service.record_receipt(
            actor_user_id=owner.id,
            business_id=created_business.id,
            receivable_id=receivable_row.id,
            payload=RecordReceiptDTO(
                received_on=date(2026, 3, 10),
                amount_received_cents=100_00,
                method=ReceiptMethod.PIX,
                note="Pago no prazo",
            ),
        )

        refreshed = service._get_receivable(business_id=created_business.id, receivable_id=receivable_row.id)
        assert refreshed.status.value == "PAID"
        assert refreshed.paid_on == date(2026, 3, 10)
    finally:
        db.close()


def test_member_suspension_cascades_to_existing_subscription() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="cascade@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = BusinessControlWorkspaceService(db)
        created_business = service.create_business(
            actor_user_id=owner.id,
            payload=CreateBusinessDTO(name="Empresa Cascade", slug="empresa-cascade"),
        )
        created_member = service.create_member(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=CreateMemberDTO(
                full_name="Cliente Cascade",
                status=MemberStatus.ACTIVE,
                joined_on=date(2026, 3, 1),
            ),
        )
        created_plan = service.create_membership_plan(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=UpsertMembershipPlanDTO(
                name="Plano Cascade",
                cadence=BillingCadence.MONTHLY,
                recurring_amount_cents=75_00,
                activation_fee_cents=0,
                billing_day=12,
                grace_days=0,
            ),
        )
        created_subscription = service.create_subscription(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=CreateSubscriptionDTO(
                member_id=created_member.id,
                membership_plan_id=created_plan.id,
                started_on=date(2026, 3, 1),
                first_due_on=date(2026, 3, 12),
                price_override_cents=None,
                notes=None,
            ),
        )

        service.set_member_status(
            actor_user_id=owner.id,
            business_id=created_business.id,
            member_id=created_member.id,
            status=MemberStatus.SUSPENDED,
        )

        refreshed_subscription = db.get(Subscription, created_subscription.id)
        assert refreshed_subscription is not None
        assert refreshed_subscription.status == SubscriptionStatus.SUSPENDED
    finally:
        db.close()
