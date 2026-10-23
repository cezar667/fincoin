from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.application.dto.business_control_dto import CreateBusinessDTO, UpsertMembershipPlanDTO
from app.application.use_cases.themembers_integration import TheMembersIntegrationService
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import (
    audit_log,
    business,
    business_account,
    business_category,
    business_integration,
    cost_center,
    member,
    membership_plan,
    receipt,
    receivable,
    subscription,
    user,
    webhook_event,
)
from app.infrastructure.db.models.enums import BillingCadence, MemberStatus, SubscriptionStatus
from app.infrastructure.db.models.member import Member
from app.infrastructure.db.models.membership_plan import MembershipPlan
from app.infrastructure.db.models.receipt import Receipt
from app.infrastructure.db.models.receivable import Receivable
from app.infrastructure.db.models.subscription import Subscription
from app.infrastructure.db.models.user import User
from app.infrastructure.db.models.webhook_event import WebhookEvent

_ = (
    audit_log,
    business,
    business_account,
    business_category,
    business_integration,
    cost_center,
    member,
    membership_plan,
    receipt,
    receivable,
    subscription,
    user,
    webhook_event,
)


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _release_payload(
    *,
    invoice_code: str = "INV-001",
    transaction_id: str = "TRX-001",
    event_id: str = "evt-001",
    product_id: str = "soomei-start",
    reference_id: str = "TM-SOOMEI-START",
    title: str = "Soomei Start",
    amount: int = 4990,
    starts_at: str = "2026-03-05T10:00:00Z",
    expire_at: str = "2026-03-05T00:00:00Z",
    order_created_at: str = "2026-03-05T10:00:00Z",
    paid_at: str = "2026-03-05T10:03:00Z",
):
    return {
        "payload": {
            "id": event_id,
            "event": "release.access",
            "data": {
                "customer": {
                    "id": "cust-001",
                    "name": "Associada Webhook",
                    "email": "webhook@test.local",
                    "document": "12345678900",
                    "phone": "11999990000",
                },
                "main_product": {
                    "id": product_id,
                    "reference_id": reference_id,
                    "title": title,
                },
                "subscription": {
                    "code": "SUB-001",
                    "starts_at": starts_at,
                    "invoice": {
                        "code": invoice_code,
                        "expire_at": expire_at,
                        "amount": amount,
                    },
                },
                "transaction": {
                    "id": transaction_id,
                    "value": amount,
                    "method": "pix",
                    "paid_at": paid_at,
                },
                "order": {
                    "id": "ORD-001",
                    "total": amount,
                    "created_at": order_created_at,
                },
            },
        }
    }


def _one_time_payload(
    *,
    event_type: str = "transaction.approved",
    event_id: str = "evt-course-001",
    transaction_id: str = "TRX-COURSE-001",
    order_id: str = "ORD-COURSE-001",
    product_id: str = "curso-soomei",
    reference_id: str = "TM-CURSO-SOOMEI",
    title: str = "Curso Receita Recorrente",
    amount: int = 2990,
    created_at: str = "2026-03-05T11:00:00Z",
    paid_at: str = "2026-03-05T11:01:00Z",
):
    return {
        "payload": {
            "id": event_id,
            "event": event_type,
            "data": {
                "customer": {
                    "id": "cust-002",
                    "name": "Compradora Avulsa",
                    "email": "curso@test.local",
                    "document": "98765432100",
                    "phone": "11988887777",
                },
                "main_product": {
                    "id": product_id,
                    "reference_id": reference_id,
                    "title": title,
                },
                "transaction": {
                    "id": transaction_id,
                    "value": amount,
                    "method": "pix",
                    "paid_at": paid_at,
                },
                "order": {
                    "id": order_id,
                    "total": amount,
                    "created_at": created_at,
                },
            },
        }
    }


def _cancel_payload():
    return {
        "payload": {
            "id": "evt-cancel",
            "event": "order.canceled",
            "data": {
                "customer": {"id": "cust-001", "name": "Associada Webhook", "email": "webhook@test.local"},
                "main_product": {"id": "soomei-start", "reference_id": "TM-SOOMEI-START", "title": "Soomei Start"},
                "subscription": {"code": "SUB-001"},
            },
        }
    }


def _revoke_payload():
    return {
        "payload": {
            "id": "evt-revoke",
            "event": "revoke.access",
            "data": {
                "customer": {"id": "cust-001", "name": "Associada Webhook", "email": "webhook@test.local"},
                "main_product": {"id": "soomei-start", "reference_id": "TM-SOOMEI-START", "title": "Soomei Start"},
                "subscription": {"code": "SUB-001"},
            },
        }
    }


def test_release_access_creates_member_subscription_and_paid_receivable() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="tm@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = TheMembersIntegrationService(db)
        created_business = service.create_business(
            actor_user_id=owner.id,
            payload=CreateBusinessDTO(name="Soomei", slug="soomei-tm"),
        )
        service.create_membership_plan(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=UpsertMembershipPlanDTO(
                name="Soomei Start",
                description="Plano integrado",
                external_product_id="soomei-start",
                external_reference_id="TM-SOOMEI-START",
                cadence=BillingCadence.MONTHLY,
                recurring_amount_cents=49_90,
                activation_fee_cents=0,
                billing_day=5,
                grace_days=3,
            ),
        )
        integration = service.create_checkout_integration(actor_user_id=owner.id, business_id=created_business.id)

        result = service.handle_checkout_webhook(
            webhook_path_token=integration.integration.webhook_path_token,
            signature=integration.webhook_secret or "",
            body=_release_payload(),
            request_id="req-release",
            source_ip="127.0.0.1",
            user_agent="pytest",
            headers={"X-Signature": integration.webhook_secret or ""},
        )

        assert result.status == "processed"
        member_row = db.scalar(select(Member).where(Member.business_id == created_business.id))
        assert member_row is not None
        assert member_row.external_customer_id == "cust-001"
        assert member_row.status == MemberStatus.ACTIVE

        subscription_row = db.scalar(select(Subscription).where(Subscription.business_id == created_business.id))
        assert subscription_row is not None
        assert subscription_row.external_subscription_id == "SUB-001"
        assert subscription_row.status == SubscriptionStatus.ACTIVE
        assert subscription_row.next_billing_on == date(2026, 4, 5)

        receivable_row = db.scalar(select(Receivable).where(Receivable.business_id == created_business.id))
        assert receivable_row is not None
        assert receivable_row.external_invoice_id == "INV-001"
        assert receivable_row.status.value == "PAID"

        receipt_row = db.scalar(select(Receipt).where(Receipt.business_id == created_business.id))
        assert receipt_row is not None
        assert receipt_row.external_transaction_id == "TRX-001"
    finally:
        db.close()


def test_release_access_with_yearly_plan_advances_next_billing_by_12_months() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="annual@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = TheMembersIntegrationService(db)
        created_business = service.create_business(
            actor_user_id=owner.id,
            payload=CreateBusinessDTO(name="Soomei", slug="soomei-annual"),
        )
        service.create_membership_plan(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=UpsertMembershipPlanDTO(
                name="Soomei Annual",
                description="Plano anual integrado",
                external_product_id="soomei-annual",
                external_reference_id="TM-SOOMEI-ANNUAL",
                cadence=BillingCadence.YEARLY,
                recurring_amount_cents=155_88,
                activation_fee_cents=0,
                billing_day=5,
                grace_days=3,
            ),
        )
        integration = service.create_checkout_integration(actor_user_id=owner.id, business_id=created_business.id)

        result = service.handle_checkout_webhook(
            webhook_path_token=integration.integration.webhook_path_token,
            signature=integration.webhook_secret or "",
            body=_release_payload(
                invoice_code="INV-ANNUAL-001",
                transaction_id="TRX-ANNUAL-001",
                event_id="evt-annual-001",
                product_id="soomei-annual",
                reference_id="TM-SOOMEI-ANNUAL",
                title="Soomei Annual",
                amount=155_88,
            ),
            request_id="req-annual",
            source_ip="127.0.0.1",
            user_agent="pytest",
        )

        subscription_row = db.scalar(select(Subscription).where(Subscription.business_id == created_business.id))

        assert result.status == "processed"
        assert subscription_row is not None
        assert subscription_row.next_billing_on == date(2027, 3, 5)
    finally:
        db.close()


def test_transaction_approved_without_subscription_creates_one_time_sale() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="course@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = TheMembersIntegrationService(db)
        created_business = service.create_business(
            actor_user_id=owner.id,
            payload=CreateBusinessDTO(name="Soomei", slug="soomei-courses"),
        )
        integration = service.create_checkout_integration(actor_user_id=owner.id, business_id=created_business.id)

        result = service.handle_checkout_webhook(
            webhook_path_token=integration.integration.webhook_path_token,
            signature=integration.webhook_secret or "",
            body=_one_time_payload(),
            request_id="req-course",
            source_ip="127.0.0.1",
            user_agent="pytest",
        )

        receivable_row = db.scalar(select(Receivable).where(Receivable.business_id == created_business.id))
        receipt_row = db.scalar(select(Receipt).where(Receipt.business_id == created_business.id))

        assert result.status == "processed"
        assert db.scalar(select(Member).where(Member.business_id == created_business.id)) is not None
        assert len(list(db.scalars(select(Subscription).where(Subscription.business_id == created_business.id)))) == 0
        assert receivable_row is not None
        assert receivable_row.subscription_id is None
        assert receivable_row.kind.value == "ADJUSTMENT"
        assert "Curso Receita Recorrente" in receivable_row.description
        assert receivable_row.status.value == "PAID"
        assert receipt_row is not None
        assert receipt_row.external_transaction_id == "TRX-COURSE-001"
    finally:
        db.close()


def test_duplicate_event_is_idempotent() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="dup@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = TheMembersIntegrationService(db)
        created_business = service.create_business(
            actor_user_id=owner.id,
            payload=CreateBusinessDTO(name="Soomei", slug="soomei-dup"),
        )
        service.create_membership_plan(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=UpsertMembershipPlanDTO(
                name="Soomei Start",
                external_product_id="soomei-start",
                external_reference_id="TM-SOOMEI-START",
                cadence=BillingCadence.MONTHLY,
                recurring_amount_cents=49_90,
                activation_fee_cents=0,
                billing_day=5,
                grace_days=3,
            ),
        )
        integration = service.create_checkout_integration(actor_user_id=owner.id, business_id=created_business.id)
        payload = _release_payload()

        first = service.handle_checkout_webhook(
            webhook_path_token=integration.integration.webhook_path_token,
            signature=integration.webhook_secret or "",
            body=payload,
            request_id="req-1",
            source_ip="127.0.0.1",
            user_agent="pytest",
        )
        second = service.handle_checkout_webhook(
            webhook_path_token=integration.integration.webhook_path_token,
            signature=integration.webhook_secret or "",
            body=payload,
            request_id="req-2",
            source_ip="127.0.0.1",
            user_agent="pytest",
        )

        assert first.status == "processed"
        assert second.status == "duplicate"
        assert len(list(db.scalars(select(Member)))) == 1
        assert len(list(db.scalars(select(Subscription)))) == 1
        assert len(list(db.scalars(select(Receivable)))) == 1
        assert len(list(db.scalars(select(Receipt)))) == 1
        assert len(list(db.scalars(select(WebhookEvent)))) == 1
    finally:
        db.close()


def test_cancel_request_and_revoke_access_update_statuses() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="cancel@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = TheMembersIntegrationService(db)
        created_business = service.create_business(
            actor_user_id=owner.id,
            payload=CreateBusinessDTO(name="Soomei", slug="soomei-cancel"),
        )
        service.create_membership_plan(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=UpsertMembershipPlanDTO(
                name="Soomei Start",
                external_product_id="soomei-start",
                external_reference_id="TM-SOOMEI-START",
                cadence=BillingCadence.MONTHLY,
                recurring_amount_cents=49_90,
                activation_fee_cents=0,
                billing_day=5,
                grace_days=3,
            ),
        )
        integration = service.create_checkout_integration(actor_user_id=owner.id, business_id=created_business.id)
        service.handle_checkout_webhook(
            webhook_path_token=integration.integration.webhook_path_token,
            signature=integration.webhook_secret or "",
            body=_release_payload(),
            request_id="req-release",
            source_ip="127.0.0.1",
            user_agent="pytest",
        )

        cancel_result = service.handle_checkout_webhook(
            webhook_path_token=integration.integration.webhook_path_token,
            signature=integration.webhook_secret or "",
            body=_cancel_payload(),
            request_id="req-cancel",
            source_ip="127.0.0.1",
            user_agent="pytest",
        )
        revoke_result = service.handle_checkout_webhook(
            webhook_path_token=integration.integration.webhook_path_token,
            signature=integration.webhook_secret or "",
            body=_revoke_payload(),
            request_id="req-revoke",
            source_ip="127.0.0.1",
            user_agent="pytest",
        )

        subscription_row = db.scalar(select(Subscription).where(Subscription.business_id == created_business.id))
        member_row = db.scalar(select(Member).where(Member.business_id == created_business.id))
        assert cancel_result.status == "processed"
        assert revoke_result.status == "processed"
        assert subscription_row is not None and subscription_row.status == SubscriptionStatus.CANCELED
        assert member_row is not None and member_row.status == MemberStatus.CANCELED
        assert subscription_row.cancel_requested_at is not None
    finally:
        db.close()


def test_failed_event_can_be_reprocessed_after_plan_mapping_fix() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="reprocess@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = TheMembersIntegrationService(db)
        created_business = service.create_business(
            actor_user_id=owner.id,
            payload=CreateBusinessDTO(name="Soomei", slug="soomei-reprocess"),
        )
        service.create_membership_plan(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=UpsertMembershipPlanDTO(
                name="Plano Interno",
                cadence=BillingCadence.MONTHLY,
                recurring_amount_cents=49_90,
                activation_fee_cents=0,
                billing_day=5,
                grace_days=3,
            ),
        )
        integration = service.create_checkout_integration(actor_user_id=owner.id, business_id=created_business.id)

        failed = service.handle_checkout_webhook(
            webhook_path_token=integration.integration.webhook_path_token,
            signature=integration.webhook_secret or "",
            body=_release_payload(),
            request_id="req-failed",
            source_ip="127.0.0.1",
            user_agent="pytest",
        )
        assert failed.status == "failed"

        plan_row = db.scalar(select(MembershipPlan).where(MembershipPlan.business_id == created_business.id))
        assert plan_row is not None
        service.update_membership_plan(
            actor_user_id=owner.id,
            business_id=created_business.id,
            plan_id=plan_row.id,
            payload=UpsertMembershipPlanDTO(
                name=plan_row.name,
                description=plan_row.description,
                external_product_id="soomei-start",
                external_reference_id="TM-SOOMEI-START",
                cadence=plan_row.cadence,
                recurring_amount_cents=plan_row.recurring_amount_cents,
                activation_fee_cents=plan_row.activation_fee_cents,
                billing_day=plan_row.billing_day,
                grace_days=plan_row.grace_days,
            ),
        )

        retried = service.reprocess_checkout_event(
            actor_user_id=owner.id,
            business_id=created_business.id,
            event_id=failed.event.id,
            request_id="req-reprocess",
        )

        assert retried.status == "processed"
        assert db.scalar(select(Member)) is not None
        assert db.scalar(select(Subscription)) is not None
        refreshed_event = db.get(WebhookEvent, failed.event.id)
        assert refreshed_event is not None
        assert refreshed_event.status.value == "PROCESSED"
    finally:
        db.close()


def test_invalid_signature_is_rejected() -> None:
    db = _build_session()
    try:
        owner = User(id=uuid4(), email="invalid@test.local", password_hash="hash")
        db.add(owner)
        db.commit()

        service = TheMembersIntegrationService(db)
        created_business = service.create_business(
            actor_user_id=owner.id,
            payload=CreateBusinessDTO(name="Soomei", slug="soomei-invalid"),
        )
        service.create_membership_plan(
            actor_user_id=owner.id,
            business_id=created_business.id,
            payload=UpsertMembershipPlanDTO(
                name="Soomei Start",
                external_product_id="soomei-start",
                external_reference_id="TM-SOOMEI-START",
                cadence=BillingCadence.MONTHLY,
                recurring_amount_cents=49_90,
                activation_fee_cents=0,
                billing_day=5,
                grace_days=3,
            ),
        )
        integration = service.create_checkout_integration(actor_user_id=owner.id, business_id=created_business.id)

        with pytest.raises(PermissionError):
            service.handle_checkout_webhook(
                webhook_path_token=integration.integration.webhook_path_token,
                signature="token-invalido",
                body=_release_payload(event_id="evt-invalid"),
                request_id="req-invalid",
                source_ip="127.0.0.1",
                user_agent="pytest",
            )
    finally:
        db.close()
