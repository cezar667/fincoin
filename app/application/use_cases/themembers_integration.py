import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.application.use_cases.business_control_phase2 import BusinessControlWorkspaceService
from app.domain.value_objects.month import Month
from app.infrastructure.auth.webhook import (
    build_secret_hint,
    generate_webhook_path_token,
    generate_webhook_secret,
    hash_webhook_secret,
    verify_webhook_secret,
)
from app.infrastructure.db.base import utc_now
from app.infrastructure.db.models.business_integration import BusinessIntegration
from app.infrastructure.db.models.enums import (
    AuditAction,
    IntegrationProvider,
    MemberStatus,
    ReceiptMethod,
    ReceivableKind,
    ReceivableStatus,
    SubscriptionStatus,
    WebhookEventStatus,
)
from app.infrastructure.db.models.member import Member
from app.infrastructure.db.models.membership_plan import MembershipPlan
from app.infrastructure.db.models.receipt import Receipt
from app.infrastructure.db.models.receivable import Receivable
from app.infrastructure.db.models.subscription import Subscription
from app.infrastructure.db.models.webhook_event import WebhookEvent
from app.infrastructure.settings.config import get_settings


THEMEMBERS_PROVIDER = IntegrationProvider.THEMEMBERS_CHECKOUT


@dataclass(slots=True)
class ProvisionedIntegration:
    integration: BusinessIntegration
    webhook_url: str
    webhook_secret: str | None


@dataclass(slots=True)
class WebhookProcessingResult:
    event: WebhookEvent
    status: str
    detail: str


class TheMembersIntegrationService(BusinessControlWorkspaceService):
    def create_checkout_integration(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        request_id: str | None = None,
    ) -> ProvisionedIntegration:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        existing = self._get_business_integration(business_id=business_id, required=False)
        if existing is not None:
            raise ValueError("A integracao do TheMembers ja foi provisionada para este business.")
        settings = get_settings()
        webhook_secret = generate_webhook_secret()
        row = BusinessIntegration(
            business_id=business_id,
            provider=THEMEMBERS_PROVIDER,
            display_name="TheMembers Checkout",
            webhook_path_token=generate_webhook_path_token(),
            webhook_secret_hash=hash_webhook_secret(secret=webhook_secret, pepper=settings.secret_key),
            webhook_secret_hint=build_secret_hint(webhook_secret),
            is_active=True,
            last_received_at=None,
            last_processed_at=None,
            last_error=None,
        )
        self.db.add(row)
        self.db.flush()
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.CREATE,
            entity_type="BusinessIntegration",
            entity_id=row.id,
            summary="Integracao do TheMembers provisionada.",
            details={
                "provider": row.provider.value,
                "webhook_path_token": row.webhook_path_token,
                "webhook_secret_hint": row.webhook_secret_hint,
            },
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return ProvisionedIntegration(
            integration=row,
            webhook_url=self.build_checkout_webhook_url(row),
            webhook_secret=webhook_secret,
        )

    def rotate_checkout_secret(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        request_id: str | None = None,
    ) -> ProvisionedIntegration:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        row = self._get_business_integration(business_id=business_id)
        settings = get_settings()
        webhook_secret = generate_webhook_secret()
        row.webhook_secret_hash = hash_webhook_secret(secret=webhook_secret, pepper=settings.secret_key)
        row.webhook_secret_hint = build_secret_hint(webhook_secret)
        row.last_error = None
        self.db.add(row)
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.UPDATE,
            entity_type="BusinessIntegration",
            entity_id=row.id,
            summary="Token do TheMembers rotacionado.",
            details={"provider": row.provider.value, "webhook_secret_hint": row.webhook_secret_hint},
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return ProvisionedIntegration(
            integration=row,
            webhook_url=self.build_checkout_webhook_url(row),
            webhook_secret=webhook_secret,
        )

    def get_checkout_integration(
        self,
        *,
        owner_user_id: UUID,
        business_id: UUID,
    ) -> BusinessIntegration | None:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        return self._get_business_integration(business_id=business_id, required=False)

    def list_checkout_events(
        self,
        *,
        owner_user_id: UUID,
        business_id: UUID,
        limit: int = 30,
    ) -> list[WebhookEvent]:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        integration = self._get_business_integration(business_id=business_id, required=False)
        if integration is None:
            return []
        stmt = (
            select(WebhookEvent)
            .where(WebhookEvent.business_integration_id == integration.id)
            .order_by(WebhookEvent.created_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    @staticmethod
    def build_checkout_webhook_url(integration: BusinessIntegration) -> str:
        settings = get_settings()
        base = settings.base_url.rstrip("/")
        return f"{base}/api/integrations/themembers/{integration.webhook_path_token}/checkout-webhook"

    def handle_checkout_webhook(
        self,
        *,
        webhook_path_token: str,
        signature: str,
        body: dict[str, Any],
        request_id: str | None,
        source_ip: str | None,
        user_agent: str | None,
        headers: dict[str, str] | None = None,
    ) -> WebhookProcessingResult:
        integration = self._get_business_integration_by_token(webhook_path_token=webhook_path_token)
        self._verify_checkout_signature(integration=integration, signature=signature)

        payload_root = self._payload_root(body)
        event_type = str(payload_root.get("event") or payload_root.get("type") or "").strip()
        if not event_type:
            raise ValueError("Evento do TheMembers nao informado no payload.")

        event_key = self._build_event_key(payload_root)
        body_sha256 = self._body_sha256(body)
        existing = self.db.scalar(
            select(WebhookEvent).where(
                WebhookEvent.business_integration_id == integration.id,
                WebhookEvent.event_key == event_key,
            )
        )
        integration.last_received_at = utc_now()
        self.db.add(integration)

        if existing is not None and existing.status != WebhookEventStatus.FAILED:
            self.db.commit()
            return WebhookProcessingResult(
                event=existing,
                status="duplicate",
                detail="Evento ja tratado anteriormente.",
            )

        if existing is None:
            event = WebhookEvent(
                business_integration_id=integration.id,
                business_id=integration.business_id,
                provider=integration.provider,
                event_type=event_type,
                event_key=event_key,
                external_event_id=self._string_value(payload_root.get("id")),
                status=WebhookEventStatus.RECEIVED,
                payload=body,
                headers=self._sanitize_headers(headers),
                body_sha256=body_sha256,
                retry_count=0,
                request_id=request_id,
                source_ip=source_ip,
                user_agent=user_agent,
                processed_at=None,
                error_message=None,
            )
            self.db.add(event)
            self.db.flush()
        else:
            event = existing
            event.event_type = event_type
            event.payload = body
            event.headers = self._sanitize_headers(headers)
            event.body_sha256 = body_sha256
            event.retry_count += 1
            event.request_id = request_id
            event.source_ip = source_ip
            event.user_agent = user_agent
            event.status = WebhookEventStatus.RECEIVED
            event.error_message = None
            event.processed_at = None
            self.db.add(event)
            self.db.flush()

        try:
            event_status, detail = self._process_checkout_event(
                integration=integration,
                event=event,
                payload_root=payload_root,
            )
            event.status = event_status
            event.error_message = None
            event.processed_at = utc_now()
            integration.last_processed_at = event.processed_at
            integration.last_error = None if event_status != WebhookEventStatus.FAILED else detail
            self.db.add_all([integration, event])
            self.db.commit()
            self.db.refresh(event)
            return WebhookProcessingResult(event=event, status=event.status.value.lower(), detail=detail)
        except Exception as exc:
            event.status = WebhookEventStatus.FAILED
            event.error_message = str(exc)[:500]
            event.processed_at = utc_now()
            integration.last_error = event.error_message
            self.db.add_all([integration, event])
            self.db.commit()
            self.db.refresh(event)
            return WebhookProcessingResult(event=event, status="failed", detail=event.error_message or "Falha")

    def reprocess_checkout_event(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        event_id: UUID,
        request_id: str | None = None,
    ) -> WebhookProcessingResult:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        event = self.db.scalar(
            select(WebhookEvent).where(
                WebhookEvent.id == event_id,
                WebhookEvent.business_id == business_id,
                WebhookEvent.provider == THEMEMBERS_PROVIDER,
            )
        )
        if event is None:
            raise ValueError("Evento de integracao nao encontrado.")
        integration = self._get_business_integration(business_id=business_id)
        payload_root = self._payload_root(event.payload)
        event.retry_count += 1
        event.request_id = request_id
        event.error_message = None
        event.status = WebhookEventStatus.RECEIVED
        event.processed_at = None
        self.db.add(event)
        try:
            status, detail = self._process_checkout_event(
                integration=integration,
                event=event,
                payload_root=payload_root,
            )
            event.status = status
            event.processed_at = utc_now()
            integration.last_processed_at = event.processed_at
            integration.last_error = None if status != WebhookEventStatus.FAILED else detail
            self.db.add_all([integration, event])
            self._add_audit(
                business_id=business_id,
                actor_user_id=actor_user_id,
                action=AuditAction.UPDATE,
                entity_type="WebhookEvent",
                entity_id=event.id,
                summary="Evento do TheMembers reprocessado manualmente.",
                details={"event_type": event.event_type, "status": status.value},
                request_id=request_id,
            )
            self.db.commit()
            self.db.refresh(event)
            return WebhookProcessingResult(event=event, status=status.value.lower(), detail=detail)
        except Exception as exc:
            event.status = WebhookEventStatus.FAILED
            event.processed_at = utc_now()
            event.error_message = str(exc)[:500]
            integration.last_error = event.error_message
            self.db.add_all([integration, event])
            self.db.commit()
            self.db.refresh(event)
            return WebhookProcessingResult(event=event, status="failed", detail=event.error_message or "Falha")

    def _process_checkout_event(
        self,
        *,
        integration: BusinessIntegration,
        event: WebhookEvent,
        payload_root: dict[str, Any],
    ) -> tuple[WebhookEventStatus, str]:
        event_type = event.event_type
        if event_type == "release.access":
            return self._process_release_access(integration=integration, event=event, payload_root=payload_root)
        if event_type == "transaction.approved":
            return self._process_transaction_approved(integration=integration, event=event, payload_root=payload_root)
        if event_type in {"order.canceled", "subscription.canceled"}:
            return self._process_cancel_request(integration=integration, event=event, payload_root=payload_root)
        if event_type == "revoke.access":
            return self._process_revoke_access(integration=integration, event=event, payload_root=payload_root)
        if event_type in {"transaction.refunded", "transaction.charged_back", "transaction.pending_refund"}:
            return self._process_refund_event(integration=integration, event=event, payload_root=payload_root)
        return WebhookEventStatus.IGNORED, f"Evento '{event_type}' registrado sem rotina dedicada."

    def _process_release_access(
        self,
        *,
        integration: BusinessIntegration,
        event: WebhookEvent,
        payload_root: dict[str, Any],
    ) -> tuple[WebhookEventStatus, str]:
        data = self._payload_data(payload_root)
        member = self._upsert_member_from_payload(
            business_id=integration.business_id,
            data=data,
            status=MemberStatus.ACTIVE,
            request_id=event.request_id,
        )
        plan = None
        subscription = None
        if self._payload_has_subscription(data):
            plan = self._resolve_plan_from_payload(business_id=integration.business_id, data=data)
            subscription = self._upsert_subscription_from_payload(
                business_id=integration.business_id,
                member=member,
                plan=plan,
                data=data,
                request_id=event.request_id,
            )
        if self._has_order_payment(data):
            if plan is not None and subscription is not None:
                self._sync_subscription_payment_from_payload(
                    business_id=integration.business_id,
                    member=member,
                    plan=plan,
                    subscription=subscription,
                    data=data,
                    request_id=event.request_id,
                )
            else:
                self._sync_one_time_payment_from_payload(
                    business_id=integration.business_id,
                    member=member,
                    data=data,
                    request_id=event.request_id,
                )
        return WebhookEventStatus.PROCESSED, f"Acesso liberado para '{member.full_name}'."

    def _process_transaction_approved(
        self,
        *,
        integration: BusinessIntegration,
        event: WebhookEvent,
        payload_root: dict[str, Any],
    ) -> tuple[WebhookEventStatus, str]:
        data = self._payload_data(payload_root)
        member = self._upsert_member_from_payload(
            business_id=integration.business_id,
            data=data,
            status=MemberStatus.ACTIVE,
            request_id=event.request_id,
        )
        if not self._has_order_payment(data):
            return WebhookEventStatus.IGNORED, "Pagamento aprovado sem dados suficientes para conciliacao."
        if self._payload_has_subscription(data):
            plan = self._resolve_plan_from_payload(business_id=integration.business_id, data=data)
            subscription = self._upsert_subscription_from_payload(
                business_id=integration.business_id,
                member=member,
                plan=plan,
                data=data,
                request_id=event.request_id,
            )
            self._sync_subscription_payment_from_payload(
                business_id=integration.business_id,
                member=member,
                plan=plan,
                subscription=subscription,
                data=data,
                request_id=event.request_id,
            )
        else:
            self._sync_one_time_payment_from_payload(
                business_id=integration.business_id,
                member=member,
                data=data,
                request_id=event.request_id,
            )
        return WebhookEventStatus.PROCESSED, f"Pagamento conciliado para '{member.full_name}'."

    def _process_cancel_request(
        self,
        *,
        integration: BusinessIntegration,
        event: WebhookEvent,
        payload_root: dict[str, Any],
    ) -> tuple[WebhookEventStatus, str]:
        data = self._payload_data(payload_root)
        member = self._upsert_member_from_payload(
            business_id=integration.business_id,
            data=data,
            status=MemberStatus.SUSPENDED,
            request_id=event.request_id,
        )
        subscription = self._find_subscription_from_payload(
            business_id=integration.business_id,
            member=member,
            data=data,
        )
        if subscription is None:
            return WebhookEventStatus.IGNORED, "Cancelamento recebido sem assinatura mapeada."
        previous_status = subscription.status
        subscription.cancel_requested_at = utc_now()
        if subscription.status == SubscriptionStatus.ACTIVE:
            subscription.status = SubscriptionStatus.SUSPENDED
        member.status = MemberStatus.SUSPENDED
        self.db.add_all([member, subscription])
        self._add_audit(
            business_id=integration.business_id,
            actor_user_id=None,
            action=AuditAction.UPDATE,
            entity_type="Subscription",
            entity_id=subscription.id,
            summary="Pedido de cancelamento recebido via TheMembers.",
            details={"before": previous_status.value, "after": subscription.status.value},
            request_id=event.request_id,
        )
        return WebhookEventStatus.PROCESSED, f"Pedido de cancelamento marcado para '{member.full_name}'."

    def _process_revoke_access(
        self,
        *,
        integration: BusinessIntegration,
        event: WebhookEvent,
        payload_root: dict[str, Any],
    ) -> tuple[WebhookEventStatus, str]:
        data = self._payload_data(payload_root)
        member = self._upsert_member_from_payload(
            business_id=integration.business_id,
            data=data,
            status=MemberStatus.CANCELED,
            request_id=event.request_id,
        )
        subscription = self._find_subscription_from_payload(
            business_id=integration.business_id,
            member=member,
            data=data,
        )
        if subscription is not None:
            previous_status = subscription.status
            subscription.cancel_requested_at = subscription.cancel_requested_at or utc_now()
            subscription.status = SubscriptionStatus.CANCELED
            subscription.canceled_on = date.today()
            self.db.add(subscription)
            self._add_audit(
                business_id=integration.business_id,
                actor_user_id=None,
                action=AuditAction.UPDATE,
                entity_type="Subscription",
                entity_id=subscription.id,
                summary="Acesso revogado via TheMembers.",
                details={"before": previous_status.value, "after": subscription.status.value},
                request_id=event.request_id,
            )
        return WebhookEventStatus.PROCESSED, f"Acesso revogado para '{member.full_name}'."

    def _process_refund_event(
        self,
        *,
        integration: BusinessIntegration,
        event: WebhookEvent,
        payload_root: dict[str, Any],
    ) -> tuple[WebhookEventStatus, str]:
        data = self._payload_data(payload_root)
        transaction = data.get("transaction") or {}
        external_transaction_id = self._string_value(transaction.get("id"))
        if external_transaction_id is None:
            return WebhookEventStatus.IGNORED, "Evento de estorno sem transaction.id."
        receipt = self.db.scalar(
            select(Receipt).where(
                Receipt.business_id == integration.business_id,
                Receipt.external_transaction_id == external_transaction_id,
            )
        )
        if receipt is None:
            return WebhookEventStatus.IGNORED, "Pagamento estornado ainda nao conciliado no FinSight."
        receivable = receipt.receivable
        receivable.status = ReceivableStatus.REFUNDED
        self.db.add(receivable)
        self._add_audit(
            business_id=integration.business_id,
            actor_user_id=None,
            action=AuditAction.UPDATE,
            entity_type="Receivable",
            entity_id=receivable.id,
            summary="Titulo marcado como estornado via TheMembers.",
            details={"external_transaction_id": external_transaction_id},
            request_id=event.request_id,
        )
        return WebhookEventStatus.PROCESSED, f"Estorno conciliado para '{receivable.description}'."

    def _sync_subscription_payment_from_payload(
        self,
        *,
        business_id: UUID,
        member: Member,
        plan: MembershipPlan,
        subscription: Subscription,
        data: dict[str, Any],
        request_id: str | None,
    ) -> None:
        transaction = data.get("transaction") or {}
        order = data.get("order") or {}
        subscription_data = data.get("subscription") or {}
        invoice = subscription_data.get("invoice") or {}

        due_on = self._coerce_date(
            invoice.get("expire_at")
            or order.get("created_at")
            or transaction.get("paid_at")
            or transaction.get("created_at")
        ) or date.today()
        issued_on = self._coerce_date(order.get("created_at") or transaction.get("created_at")) or due_on
        amount_cents = self._cents_value(
            transaction.get("value")
            or invoice.get("amount")
            or order.get("total")
            or plan.recurring_amount_cents
        )
        if amount_cents <= 0:
            raise ValueError("Valor do pagamento invalido no payload do TheMembers.")

        receivable = self._get_or_create_external_receivable(
            business_id=business_id,
            member=member,
            subscription=subscription,
            kind=ReceivableKind.RECURRING,
            description=f"Checkout TheMembers - {plan.name} - {member.full_name}",
            amount_cents=amount_cents,
            due_on=due_on,
            issued_on=issued_on,
            external_invoice_id=self._string_value(invoice.get("code")),
            external_order_id=self._string_value(order.get("id")),
        )
        receipt = self._record_external_receipt(
            business_id=business_id,
            receivable=receivable,
            transaction=transaction,
            fallback_amount_cents=amount_cents,
            fallback_received_on=self._coerce_date(transaction.get("paid_at")) or due_on,
        )
        if receipt is not None and subscription.status == SubscriptionStatus.ACTIVE:
            subscription.next_billing_on = self._advance_billing_date(
                current_due_on=due_on,
                cadence=plan.cadence,
                billing_day=plan.billing_day,
            )
            self.db.add(subscription)
            self._add_audit(
                business_id=business_id,
                actor_user_id=None,
                action=AuditAction.UPDATE,
                entity_type="Subscription",
                entity_id=subscription.id,
                summary="Assinatura conciliada com pagamento do TheMembers.",
                details={"next_billing_on": subscription.next_billing_on.isoformat()},
                request_id=request_id,
            )

    def _sync_one_time_payment_from_payload(
        self,
        *,
        business_id: UUID,
        member: Member,
        data: dict[str, Any],
        request_id: str | None,
    ) -> None:
        transaction = data.get("transaction") or {}
        order = data.get("order") or {}
        due_on = self._coerce_date(order.get("created_at") or transaction.get("paid_at") or transaction.get("created_at")) or date.today()
        issued_on = self._coerce_date(order.get("created_at") or transaction.get("created_at")) or due_on
        amount_cents = self._cents_value(transaction.get("value") or order.get("total"))
        if amount_cents <= 0:
            raise ValueError("Valor do pagamento invalido no payload do TheMembers.")

        title = self._checkout_item_title(data)
        receivable = self._get_or_create_external_receivable(
            business_id=business_id,
            member=member,
            subscription=None,
            kind=ReceivableKind.ADJUSTMENT,
            description=f"Produto TheMembers - {title} - {member.full_name}",
            amount_cents=amount_cents,
            due_on=due_on,
            issued_on=issued_on,
            external_invoice_id=self._string_value((data.get("invoice") or {}).get("code")),
            external_order_id=self._string_value(order.get("id")),
        )
        receipt = self._record_external_receipt(
            business_id=business_id,
            receivable=receivable,
            transaction=transaction,
            fallback_amount_cents=amount_cents,
            fallback_received_on=self._coerce_date(transaction.get("paid_at")) or due_on,
        )
        if receipt is not None:
            self._add_audit(
                business_id=business_id,
                actor_user_id=None,
                action=AuditAction.CREATE,
                entity_type="Receivable",
                entity_id=receivable.id,
                summary="Venda avulsa conciliada via TheMembers.",
                details={"description": receivable.description, "amount_cents": amount_cents},
                request_id=request_id,
            )

    def _get_or_create_external_receivable(
        self,
        *,
        business_id: UUID,
        member: Member,
        subscription: Subscription | None,
        kind: ReceivableKind,
        description: str,
        amount_cents: int,
        due_on: date,
        issued_on: date,
        external_invoice_id: str | None,
        external_order_id: str | None,
    ) -> Receivable:
        row = None
        if external_invoice_id:
            row = self.db.scalar(
                select(Receivable).where(
                    Receivable.business_id == business_id,
                    Receivable.external_invoice_id == external_invoice_id,
                )
            )
        if row is None and external_order_id:
            row = self.db.scalar(
                select(Receivable).where(
                    Receivable.business_id == business_id,
                    Receivable.external_order_id == external_order_id,
                )
            )
        if row is None:
            competency_month = Month.from_any_date(due_on).value
            stmt = select(Receivable).where(
                Receivable.member_id == member.id,
                Receivable.kind == kind,
                Receivable.competency_month == competency_month,
            )
            if subscription is None:
                stmt = stmt.where(
                    Receivable.subscription_id.is_(None),
                    func.lower(Receivable.description) == description.lower(),
                )
            else:
                stmt = stmt.where(Receivable.subscription_id == subscription.id)
            row = self.db.scalar(stmt)
        if row is None:
            row = self._create_receivable_row(
                business_id=business_id,
                member_id=member.id,
                subscription_id=subscription.id if subscription is not None else None,
                kind=kind,
                description=description,
                amount_cents=amount_cents,
                due_on=due_on,
                issued_on=issued_on,
            )
            self._add_audit(
                business_id=business_id,
                actor_user_id=None,
                action=AuditAction.CREATE,
                entity_type="Receivable",
                entity_id=row.id,
                summary="Titulo criado a partir do checkout do TheMembers.",
                details={"amount_cents": amount_cents, "due_on": due_on.isoformat()},
                request_id=None,
            )
        if row.amount_cents != amount_cents and self._receivable_received_cents(row) == 0:
            row.amount_cents = amount_cents
        row.description = description
        row.external_invoice_id = row.external_invoice_id or external_invoice_id
        row.external_order_id = row.external_order_id or external_order_id
        self.db.add(row)
        return row

    def _record_external_receipt(
        self,
        *,
        business_id: UUID,
        receivable: Receivable,
        transaction: dict[str, Any],
        fallback_amount_cents: int,
        fallback_received_on: date,
    ) -> Receipt | None:
        external_transaction_id = self._string_value(transaction.get("id"))
        if external_transaction_id:
            existing = self.db.scalar(
                select(Receipt).where(
                    Receipt.business_id == business_id,
                    Receipt.external_transaction_id == external_transaction_id,
                )
            )
            if existing is not None:
                return existing

        amount_received_cents = self._cents_value(transaction.get("value") or fallback_amount_cents)
        if amount_received_cents <= 0:
            return None

        existing_received = self._receivable_received_cents(receivable)
        if amount_received_cents > self._receivable_due_total(receivable) and existing_received == 0:
            receivable.amount_cents = amount_received_cents
            self.db.add(receivable)

        method = self._receipt_method_from_transaction(transaction)
        row = Receipt(
            business_id=business_id,
            receivable_id=receivable.id,
            received_on=fallback_received_on,
            amount_received_cents=amount_received_cents,
            external_transaction_id=external_transaction_id,
            method=method,
            note="Recebimento conciliado automaticamente via TheMembers.",
        )
        self.db.add(row)
        self.db.flush()

        new_total = existing_received + amount_received_cents
        due_total = self._receivable_due_total(receivable)
        receivable.paid_on = fallback_received_on if new_total >= due_total else None
        receivable.status = (
            ReceivableStatus.PAID
            if new_total >= due_total
            else self._open_receivable_status(receivable.due_on, fallback_received_on)
        )
        self.db.add(receivable)
        self._add_audit(
            business_id=business_id,
            actor_user_id=None,
            action=AuditAction.CREATE,
            entity_type="Receipt",
            entity_id=row.id,
            summary="Recebimento importado do TheMembers.",
            details={"external_transaction_id": external_transaction_id, "amount_received_cents": amount_received_cents},
            request_id=None,
        )
        return row

    def _upsert_member_from_payload(
        self,
        *,
        business_id: UUID,
        data: dict[str, Any],
        status: MemberStatus,
        request_id: str | None,
    ) -> Member:
        customer = data.get("customer") or {}
        external_customer_id = self._string_value(customer.get("id"))
        email = self._string_value(customer.get("email"))
        joined_on = self._coerce_date(customer.get("created_at") or data.get("created_at")) or date.today()

        row = None
        if external_customer_id:
            row = self.db.scalar(
                select(Member).where(
                    Member.business_id == business_id,
                    Member.external_customer_id == external_customer_id,
                )
            )
        if row is None and email:
            row = self.db.scalar(
                select(Member).where(
                    Member.business_id == business_id,
                    func.lower(Member.email) == email.lower(),
                )
            )

        full_name = self._string_value(customer.get("name")) or email or f"Cliente {external_customer_id or 'TheMembers'}"
        phone = self._string_value(customer.get("phone"))
        document_number = self._string_value(customer.get("document"))

        if row is None:
            row = Member(
                business_id=business_id,
                full_name=full_name,
                external_customer_id=external_customer_id,
                email=email,
                phone=phone,
                document_number=document_number,
                status=status,
                joined_on=joined_on,
                activated_on=joined_on if status == MemberStatus.ACTIVE else None,
                notes="Originado pelo checkout do TheMembers.",
            )
            self.db.add(row)
            self.db.flush()
            self._add_audit(
                business_id=business_id,
                actor_user_id=None,
                action=AuditAction.CREATE,
                entity_type="Member",
                entity_id=row.id,
                summary=f"Associado '{row.full_name}' sincronizado do TheMembers.",
                details={"external_customer_id": external_customer_id, "status": status.value},
                request_id=request_id,
            )
            return row

        before_status = row.status
        row.full_name = full_name
        row.external_customer_id = row.external_customer_id or external_customer_id
        row.email = row.email or email
        row.phone = row.phone or phone
        row.document_number = row.document_number or document_number
        row.status = status
        if status == MemberStatus.ACTIVE:
            row.activated_on = row.activated_on or joined_on
        self.db.add(row)
        if before_status != row.status:
            self._add_audit(
                business_id=business_id,
                actor_user_id=None,
                action=AuditAction.UPDATE,
                entity_type="Member",
                entity_id=row.id,
                summary=f"Associado '{row.full_name}' atualizado pelo TheMembers.",
                details={"before": before_status.value, "after": row.status.value},
                request_id=request_id,
            )
        return row

    def _upsert_subscription_from_payload(
        self,
        *,
        business_id: UUID,
        member: Member,
        plan: MembershipPlan,
        data: dict[str, Any],
        request_id: str | None,
    ) -> Subscription:
        subscription_data = data.get("subscription") or {}
        external_subscription_id = self._string_value(subscription_data.get("code"))
        next_due = self._coerce_date((subscription_data.get("invoice") or {}).get("expire_at"))
        started_on = self._coerce_date(subscription_data.get("starts_at") or data.get("created_at")) or date.today()

        row = self._find_subscription_from_payload(business_id=business_id, member=member, data=data)
        if row is None:
            row = self._build_subscription_row(
                business_id=business_id,
                member_id=member.id,
                membership_plan_id=plan.id,
                started_on=started_on,
                next_billing_on=next_due
                or self._advance_billing_date(
                    current_due_on=started_on,
                    cadence=plan.cadence,
                    billing_day=plan.billing_day,
                ),
                price_override_cents=None,
                notes="Originada pelo checkout do TheMembers.",
                external_subscription_id=external_subscription_id,
            )
            self.db.add(row)
            self.db.flush()
            self._add_audit(
                business_id=business_id,
                actor_user_id=None,
                action=AuditAction.CREATE,
                entity_type="Subscription",
                entity_id=row.id,
                summary=f"Assinatura de '{member.full_name}' criada via TheMembers.",
                details={"external_subscription_id": external_subscription_id, "plan_id": str(plan.id)},
                request_id=request_id,
            )
            return row

        before_status = row.status
        row.membership_plan_id = plan.id
        row.external_subscription_id = row.external_subscription_id or external_subscription_id
        row.status = SubscriptionStatus.ACTIVE
        row.cancel_requested_at = None
        row.canceled_on = None
        if next_due is not None:
            row.next_billing_on = next_due
        self.db.add(row)
        if before_status != row.status:
            self._add_audit(
                business_id=business_id,
                actor_user_id=None,
                action=AuditAction.UPDATE,
                entity_type="Subscription",
                entity_id=row.id,
                summary=f"Assinatura de '{member.full_name}' reativada pelo TheMembers.",
                details={"before": before_status.value, "after": row.status.value},
                request_id=request_id,
            )
        return row

    def _find_subscription_from_payload(
        self,
        *,
        business_id: UUID,
        member: Member,
        data: dict[str, Any],
    ) -> Subscription | None:
        subscription_data = data.get("subscription") or {}
        external_subscription_id = self._string_value(subscription_data.get("code"))
        if external_subscription_id:
            row = self.db.scalar(
                select(Subscription).where(
                    Subscription.business_id == business_id,
                    Subscription.external_subscription_id == external_subscription_id,
                )
            )
            if row is not None:
                return row
        return self.db.scalar(
            select(Subscription).where(
                Subscription.business_id == business_id,
                Subscription.member_id == member.id,
                Subscription.status != SubscriptionStatus.CANCELED,
            )
        )

    def _resolve_plan_from_payload(
        self,
        *,
        business_id: UUID,
        data: dict[str, Any],
        required: bool = True,
    ) -> MembershipPlan | None:
        product_candidates: list[dict[str, Any]] = []
        for key in ("main_product", "product"):
            value = data.get(key)
            if isinstance(value, dict):
                product_candidates.append(value)
        subscription_product = (data.get("subscription") or {}).get("product")
        if isinstance(subscription_product, dict):
            product_candidates.append(subscription_product)

        for product in product_candidates:
            reference_id = self._string_value(product.get("reference_id"))
            if reference_id:
                row = self.db.scalar(
                    select(MembershipPlan).where(
                        MembershipPlan.business_id == business_id,
                        func.lower(MembershipPlan.external_reference_id) == reference_id.lower(),
                    )
                )
                if row is not None:
                    return row
            product_id = self._string_value(product.get("id"))
            if product_id:
                row = self.db.scalar(
                    select(MembershipPlan).where(
                        MembershipPlan.business_id == business_id,
                        func.lower(MembershipPlan.external_product_id) == product_id.lower(),
                    )
                )
                if row is not None:
                    return row
            title = self._string_value(product.get("title"))
            if title:
                row = self.db.scalar(
                    select(MembershipPlan).where(
                        MembershipPlan.business_id == business_id,
                        func.lower(MembershipPlan.name) == title.lower(),
                    )
                )
                if row is not None:
                    return row
        if required:
            raise ValueError("Plano do TheMembers nao mapeado. Configure product_id ou reference_id no plano.")
        return None

    @staticmethod
    def _payload_has_subscription(data: dict[str, Any]) -> bool:
        subscription = data.get("subscription")
        if not isinstance(subscription, dict):
            return False
        if subscription.get("code") or subscription.get("starts_at") or subscription.get("invoice"):
            return True
        product = subscription.get("product")
        return isinstance(product, dict) and bool(product)

    def _checkout_item_title(self, data: dict[str, Any]) -> str:
        for key in ("main_product", "product"):
            value = data.get(key)
            if isinstance(value, dict):
                title = self._string_value(value.get("title") or value.get("name"))
                if title:
                    return title
        subscription_product = (data.get("subscription") or {}).get("product")
        if isinstance(subscription_product, dict):
            title = self._string_value(subscription_product.get("title") or subscription_product.get("name"))
            if title:
                return title
        order = data.get("order") or {}
        title = self._string_value(order.get("title") or order.get("name"))
        return title or "Produto avulso"

    def _verify_checkout_signature(self, *, integration: BusinessIntegration, signature: str) -> None:
        settings = get_settings()
        if not signature:
            raise PermissionError("Webhook do TheMembers sem token de seguranca.")
        if not verify_webhook_secret(
            candidate=signature,
            hashed_secret=integration.webhook_secret_hash,
            pepper=settings.secret_key,
        ):
            raise PermissionError("Token de seguranca do TheMembers invalido.")

    def _get_business_integration(
        self,
        *,
        business_id: UUID,
        required: bool = True,
    ) -> BusinessIntegration | None:
        row = self.db.scalar(
            select(BusinessIntegration).where(
                BusinessIntegration.business_id == business_id,
                BusinessIntegration.provider == THEMEMBERS_PROVIDER,
            )
        )
        if row is None and required:
            raise ValueError("Integracao do TheMembers ainda nao provisionada para este business.")
        return row

    def _get_business_integration_by_token(self, *, webhook_path_token: str) -> BusinessIntegration:
        row = self.db.scalar(
            select(BusinessIntegration).where(
                BusinessIntegration.provider == THEMEMBERS_PROVIDER,
                BusinessIntegration.webhook_path_token == webhook_path_token,
                BusinessIntegration.is_active.is_(True),
            )
        )
        if row is None:
            raise ValueError("Webhook do TheMembers nao encontrado.")
        return row

    @staticmethod
    def _payload_root(body: dict[str, Any]) -> dict[str, Any]:
        payload = body.get("payload") if isinstance(body, dict) else None
        if isinstance(payload, dict):
            return payload
        return body if isinstance(body, dict) else {}

    @staticmethod
    def _payload_data(payload_root: dict[str, Any]) -> dict[str, Any]:
        data = payload_root.get("data")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _sanitize_headers(headers: dict[str, str] | None) -> dict[str, Any]:
        if not headers:
            return {}
        allowed = {
            "content-type",
            "user-agent",
            "x-signature",
            "x-request-id",
            "x-forwarded-for",
        }
        return {key.lower(): value for key, value in headers.items() if key.lower() in allowed}

    def _build_event_key(self, payload_root: dict[str, Any]) -> str:
        event_type = str(payload_root.get("event") or payload_root.get("type") or "unknown").strip().lower()
        data = self._payload_data(payload_root)
        candidates = [
            self._string_value(payload_root.get("id")),
            self._string_value(data.get("id")),
            self._string_value((data.get("transaction") or {}).get("id")),
            self._string_value((data.get("order") or {}).get("id")),
            self._string_value((((data.get("subscription") or {}).get("invoice") or {}).get("code"))),
            self._string_value((data.get("subscription") or {}).get("code")),
        ]
        for candidate in candidates:
            if candidate:
                return f"{event_type}:{candidate}"
        return f"{event_type}:{self._body_sha256(payload_root)}"

    @staticmethod
    def _body_sha256(value: Any) -> str:
        canonical = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _string_value(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _coerce_date(value: Any) -> date | None:
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        text = str(value).strip()
        if not text:
            return None
        if "T" in text:
            normalized = text.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(normalized).date()
            except ValueError:
                return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None

    @staticmethod
    def _cents_value(value: Any) -> int:
        if value is None or isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(round(value * 100))
        text = str(value).strip()
        if not text:
            return 0
        normalized = text.replace(".", "").replace(",", "")
        try:
            return int(normalized)
        except ValueError:
            try:
                return int(float(text.replace(",", ".")) * 100)
            except ValueError:
                return 0

    @staticmethod
    def _receipt_method_from_transaction(transaction: dict[str, Any]) -> ReceiptMethod:
        raw = str(transaction.get("method") or transaction.get("payment_method") or "").strip().lower()
        if "pix" in raw:
            return ReceiptMethod.PIX
        if "boleto" in raw:
            return ReceiptMethod.BOLETO
        if "card" in raw or "cart" in raw or "credito" in raw:
            return ReceiptMethod.CARD
        if "cash" in raw or "dinheiro" in raw:
            return ReceiptMethod.CASH
        if "transfer" in raw or "ted" in raw:
            return ReceiptMethod.TRANSFER
        return ReceiptMethod.OTHER

    @staticmethod
    def _has_order_payment(data: dict[str, Any]) -> bool:
        return isinstance(data.get("transaction"), dict) or isinstance(data.get("order"), dict)
