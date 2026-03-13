import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select

from app.application.dto.business_control_dto import (
    CreateBusinessDTO,
    CreateMemberDTO,
    CreateSubscriptionDTO,
    RecordReceiptDTO,
    UpsertMembershipPlanDTO,
)
from app.application.use_cases.business_control import BusinessControlService
from app.domain.value_objects.month import Month
from app.infrastructure.db.models.audit_log import AuditLog
from app.infrastructure.db.models.member import Member
from app.infrastructure.db.models.membership_plan import MembershipPlan
from app.infrastructure.db.models.receipt import Receipt
from app.infrastructure.db.models.receivable import Receivable
from app.infrastructure.db.models.subscription import Subscription
from app.infrastructure.db.models.enums import (
    AuditAction,
    BillingCadence,
    MemberStatus,
    ReceivableKind,
    ReceivableStatus,
    SubscriptionStatus,
)


SOOMEI_MEMBERSHIP_PLANS = [
    {
        "name": "Soomei Start",
        "description": "Entrada simples para ativacao do associado e inicio da base recorrente.",
        "external_product_id": "soomei-start",
        "external_reference_id": "TM-SOOMEI-START",
        "cadence": BillingCadence.MONTHLY,
        "recurring_amount_cents": 49_90,
        "activation_fee_cents": 19_90,
        "billing_day": 5,
        "grace_days": 3,
    },
    {
        "name": "Soomei Prime",
        "description": "Plano com maior valor mensal para operacao premium e melhor margem.",
        "external_product_id": "soomei-prime",
        "external_reference_id": "TM-SOOMEI-PRIME",
        "cadence": BillingCadence.MONTHLY,
        "recurring_amount_cents": 89_90,
        "activation_fee_cents": 29_90,
        "billing_day": 5,
        "grace_days": 3,
    },
]


@dataclass(slots=True)
class JourneyStage:
    title: str
    caption: str
    count: int
    tone: str


@dataclass(slots=True)
class MindMapNode:
    title: str
    metric_text: str
    caption: str
    tone: str


@dataclass(slots=True)
class BusinessOperationsDashboardSummary:
    total_businesses: int
    active_businesses: int
    active_accounts: int
    active_categories: int
    active_cost_centers: int
    initial_balance_cents: int
    recent_audits: list[AuditLog]
    total_members: int
    active_members: int
    active_plans: int
    total_subscriptions: int
    active_subscriptions: int
    mrr_gross_cents: int
    expected_this_month_cents: int
    received_this_month_cents: int
    overdue_cents: int
    overdue_count: int
    open_receivables_count: int
    recent_receivables: list[Receivable]
    journey_stages: list[JourneyStage]
    mind_map_nodes: list[MindMapNode]


class BusinessControlWorkspaceService(BusinessControlService):
    def create_business(
        self,
        *,
        actor_user_id: UUID,
        payload: CreateBusinessDTO,
        request_id: str | None = None,
    ):
        business = super().create_business(
            actor_user_id=actor_user_id,
            payload=payload,
            request_id=request_id,
        )
        if payload.seed_template == "SOOMEI":
            self._ensure_soomei_membership_plans(
                actor_user_id=actor_user_id,
                business_id=business.id,
                request_id=request_id,
            )
        return business

    def build_dashboard(self, *, owner_user_id: UUID, business_id: UUID) -> BusinessOperationsDashboardSummary:
        base = super().build_dashboard(owner_user_id=owner_user_id, business_id=business_id)
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        self._refresh_overdue_receivables(business_id=business_id)

        today = date.today()
        current_month = Month.from_any_date(today).value
        next_month = Month.from_any_date(today).add_months(1).value

        total_members = int(
            self.db.scalar(select(func.count(Member.id)).where(Member.business_id == business_id)) or 0
        )
        active_members = int(
            self.db.scalar(
                select(func.count(Member.id)).where(
                    Member.business_id == business_id,
                    Member.status == MemberStatus.ACTIVE,
                )
            )
            or 0
        )
        active_plans = int(
            self.db.scalar(
                select(func.count(MembershipPlan.id)).where(
                    MembershipPlan.business_id == business_id,
                    MembershipPlan.is_active.is_(True),
                )
            )
            or 0
        )
        subscription_rows = list(
            self.db.scalars(
                select(Subscription)
                .where(Subscription.business_id == business_id)
                .order_by(Subscription.created_at.desc())
            )
        )
        total_subscriptions = len(subscription_rows)
        active_subscription_rows = [
            item for item in subscription_rows if item.status == SubscriptionStatus.ACTIVE
        ]
        mrr_gross_cents = sum(self._subscription_amount_cents(item) for item in active_subscription_rows)

        receivable_rows = list(
            self.db.scalars(
                select(Receivable)
                .where(Receivable.business_id == business_id)
                .order_by(Receivable.due_on.asc(), Receivable.created_at.desc())
            )
        )
        recent_receivables = receivable_rows[:6]
        expected_statuses = {
            ReceivableStatus.PLANNED,
            ReceivableStatus.ISSUED,
            ReceivableStatus.OVERDUE,
            ReceivableStatus.PAID,
        }
        expected_this_month_cents = sum(
            self._receivable_due_total(item)
            for item in receivable_rows
            if item.competency_month == current_month and item.status in expected_statuses
        )
        overdue_rows = [item for item in receivable_rows if item.status == ReceivableStatus.OVERDUE]
        overdue_cents = sum(self._receivable_balance_cents(item) for item in overdue_rows)
        open_receivables_count = sum(
            1
            for item in receivable_rows
            if item.status in {ReceivableStatus.PLANNED, ReceivableStatus.ISSUED, ReceivableStatus.OVERDUE}
        )
        received_this_month_cents = int(
            self.db.scalar(
                select(func.coalesce(func.sum(Receipt.amount_received_cents), 0)).where(
                    Receipt.business_id == business_id,
                    Receipt.received_on >= current_month,
                    Receipt.received_on < next_month,
                )
            )
            or 0
        )

        journey_stages = [
            JourneyStage("Entrada", "Associados cadastrados no funil do business.", total_members, "teal"),
            JourneyStage("Ativacao", "Associados ativos e aptos a consumir a operacao.", active_members, "sky"),
            JourneyStage(
                "Assinatura",
                "Assinaturas recorrentes em execucao.",
                len(active_subscription_rows),
                "emerald",
            ),
            JourneyStage(
                "Cobranca",
                "Titulos ainda abertos no contas a receber.",
                open_receivables_count,
                "amber",
            ),
            JourneyStage(
                "Recebimento",
                "Baixas recebidas no mes corrente.",
                sum(1 for item in receivable_rows if item.paid_on and current_month <= item.paid_on < next_month),
                "indigo",
            ),
            JourneyStage(
                "Risco",
                "Titulos vencidos que exigem acao de retencao.",
                len(overdue_rows),
                "rose",
            ),
        ]

        mind_map_nodes = [
            MindMapNode("MRR Bruto", self._format_brl(mrr_gross_cents), "Base recorrente das assinaturas ativas.", "teal"),
            MindMapNode("Previsto no mes", self._format_brl(expected_this_month_cents), "Competencia atual ja emitida ou planejada.", "sky"),
            MindMapNode("Recebido no mes", self._format_brl(received_this_month_cents), "Caixa efetivamente baixado.", "emerald"),
            MindMapNode("Inadimplencia", self._format_brl(overdue_cents), f"{len(overdue_rows)} titulos em atraso.", "rose"),
            MindMapNode("Planos ativos", str(active_plans), "Arquitetura comercial em oferta.", "amber"),
            MindMapNode("Contas abertas", str(open_receivables_count), "Fila operacional de cobranca.", "indigo"),
        ]

        return BusinessOperationsDashboardSummary(
            total_businesses=base.total_businesses,
            active_businesses=base.active_businesses,
            active_accounts=base.active_accounts,
            active_categories=base.active_categories,
            active_cost_centers=base.active_cost_centers,
            initial_balance_cents=base.initial_balance_cents,
            recent_audits=base.recent_audits,
            total_members=total_members,
            active_members=active_members,
            active_plans=active_plans,
            total_subscriptions=total_subscriptions,
            active_subscriptions=len(active_subscription_rows),
            mrr_gross_cents=mrr_gross_cents,
            expected_this_month_cents=expected_this_month_cents,
            received_this_month_cents=received_this_month_cents,
            overdue_cents=overdue_cents,
            overdue_count=len(overdue_rows),
            open_receivables_count=open_receivables_count,
            recent_receivables=recent_receivables,
            journey_stages=journey_stages,
            mind_map_nodes=mind_map_nodes,
        )

    def list_members(self, *, owner_user_id: UUID, business_id: UUID) -> list[Member]:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        return list(
            self.db.scalars(
                select(Member)
                .where(Member.business_id == business_id)
                .order_by(Member.created_at.desc())
            )
        )

    def create_member(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        payload: CreateMemberDTO,
        request_id: str | None = None,
    ) -> Member:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        row = Member(
            business_id=business_id,
            full_name=payload.full_name,
            email=payload.email,
            phone=payload.phone,
            document_number=payload.document_number,
            status=payload.status,
            joined_on=payload.joined_on,
            activated_on=payload.joined_on if payload.status == MemberStatus.ACTIVE else None,
            notes=payload.notes,
        )
        self.db.add(row)
        self.db.flush()
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.CREATE,
            entity_type="Member",
            entity_id=row.id,
            summary=f"Associado '{row.full_name}' cadastrado.",
            details=payload.model_dump(mode="json"),
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def set_member_status(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        member_id: UUID,
        status: MemberStatus,
        request_id: str | None = None,
    ) -> Member:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        row = self._get_member(business_id=business_id, member_id=member_id)
        if row.status == status:
            return row
        previous_status = row.status
        row.status = status
        if status == MemberStatus.ACTIVE and row.activated_on is None:
            row.activated_on = date.today()
        self.db.add(row)
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.UPDATE,
            entity_type="Member",
            entity_id=row.id,
            summary=f"Associado '{row.full_name}' alterado para {status.value}.",
            details={"before": previous_status.value, "after": status.value},
            request_id=request_id,
        )
        if status in {MemberStatus.SUSPENDED, MemberStatus.BLOCKED, MemberStatus.CANCELED}:
            self._cascade_member_status_to_subscriptions(
                actor_user_id=actor_user_id,
                member=row,
                request_id=request_id,
            )
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_membership_plans(self, *, owner_user_id: UUID, business_id: UUID) -> list[MembershipPlan]:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        return list(
            self.db.scalars(
                select(MembershipPlan)
                .where(MembershipPlan.business_id == business_id)
                .order_by(MembershipPlan.is_active.desc(), MembershipPlan.name.asc())
            )
        )

    def create_membership_plan(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        payload: UpsertMembershipPlanDTO,
        request_id: str | None = None,
    ) -> MembershipPlan:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        self._assert_membership_plan_available(
            business_id=business_id,
            name=payload.name,
            external_product_id=payload.external_product_id,
            external_reference_id=payload.external_reference_id,
        )
        row = MembershipPlan(
            business_id=business_id,
            name=payload.name,
            description=payload.description,
            external_product_id=payload.external_product_id,
            external_reference_id=payload.external_reference_id,
            cadence=payload.cadence,
            recurring_amount_cents=payload.recurring_amount_cents,
            activation_fee_cents=payload.activation_fee_cents,
            billing_day=payload.billing_day,
            grace_days=payload.grace_days,
            is_active=True,
        )
        self.db.add(row)
        self.db.flush()
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.CREATE,
            entity_type="MembershipPlan",
            entity_id=row.id,
            summary=f"Plano '{row.name}' criado.",
            details=payload.model_dump(mode="json"),
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_membership_plan(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        plan_id: UUID,
        payload: UpsertMembershipPlanDTO,
        request_id: str | None = None,
    ) -> MembershipPlan:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        row = self._get_membership_plan(business_id=business_id, plan_id=plan_id)
        self._assert_membership_plan_available(
            business_id=business_id,
            name=payload.name,
            external_product_id=payload.external_product_id,
            external_reference_id=payload.external_reference_id,
            exclude_id=row.id,
        )
        before = {
            "name": row.name,
            "description": row.description,
            "external_product_id": row.external_product_id,
            "external_reference_id": row.external_reference_id,
            "cadence": row.cadence.value,
            "recurring_amount_cents": row.recurring_amount_cents,
            "activation_fee_cents": row.activation_fee_cents,
            "billing_day": row.billing_day,
            "grace_days": row.grace_days,
            "is_active": row.is_active,
        }
        row.name = payload.name
        row.description = payload.description
        row.external_product_id = payload.external_product_id
        row.external_reference_id = payload.external_reference_id
        row.cadence = payload.cadence
        row.recurring_amount_cents = payload.recurring_amount_cents
        row.activation_fee_cents = payload.activation_fee_cents
        row.billing_day = payload.billing_day
        row.grace_days = payload.grace_days
        self.db.add(row)
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.UPDATE,
            entity_type="MembershipPlan",
            entity_id=row.id,
            summary=f"Plano '{row.name}' atualizado.",
            details={"before": before, "after": payload.model_dump(mode="json")},
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def set_membership_plan_active(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        plan_id: UUID,
        is_active: bool,
        request_id: str | None = None,
    ) -> MembershipPlan:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        row = self._get_membership_plan(business_id=business_id, plan_id=plan_id)
        if row.is_active == is_active:
            return row
        row.is_active = is_active
        self.db.add(row)
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.ACTIVATE if is_active else AuditAction.DEACTIVATE,
            entity_type="MembershipPlan",
            entity_id=row.id,
            summary=f"Plano '{row.name}' {'ativado' if is_active else 'desativado'}.",
            details={"is_active": is_active},
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_subscriptions(self, *, owner_user_id: UUID, business_id: UUID) -> list[Subscription]:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        return list(
            self.db.scalars(
                select(Subscription)
                .where(Subscription.business_id == business_id)
                .order_by(Subscription.created_at.desc())
            )
        )

    def create_subscription(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        payload: CreateSubscriptionDTO,
        request_id: str | None = None,
    ) -> Subscription:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        member = self._get_member(business_id=business_id, member_id=payload.member_id)
        plan = self._get_membership_plan(business_id=business_id, plan_id=payload.membership_plan_id)
        if not plan.is_active:
            raise ValueError("Reative o plano antes de criar assinaturas.")
        if member.status in {MemberStatus.SUSPENDED, MemberStatus.BLOCKED, MemberStatus.CANCELED}:
            raise ValueError("Reative o associado antes de criar uma assinatura.")
        existing = self.db.scalar(
            select(Subscription).where(
                Subscription.business_id == business_id,
                Subscription.member_id == member.id,
                Subscription.status != SubscriptionStatus.CANCELED,
            )
        )
        if existing is not None:
            raise ValueError("Cada associado pode ter apenas uma assinatura ativa por vez.")

        row = self._build_subscription_row(
            business_id=business_id,
            member_id=member.id,
            membership_plan_id=plan.id,
            started_on=payload.started_on,
            next_billing_on=self._add_months_with_day(payload.first_due_on, 1, plan.billing_day),
            price_override_cents=payload.price_override_cents,
            notes=payload.notes,
        )
        self.db.add(row)
        self.db.flush()

        if member.status != MemberStatus.ACTIVE:
            member.status = MemberStatus.ACTIVE
            member.activated_on = member.activated_on or payload.started_on
            self.db.add(member)

        if plan.activation_fee_cents > 0:
            self._create_receivable_row(
                business_id=business_id,
                member_id=member.id,
                subscription_id=row.id,
                kind=ReceivableKind.ACTIVATION,
                description=f"Taxa de ativacao - {member.full_name}",
                amount_cents=plan.activation_fee_cents,
                due_on=payload.started_on,
                issued_on=payload.started_on,
            )

        recurring_amount = payload.price_override_cents or plan.recurring_amount_cents
        self._create_receivable_row(
            business_id=business_id,
            member_id=member.id,
            subscription_id=row.id,
            kind=ReceivableKind.RECURRING,
            description=f"Mensalidade {plan.name} - {member.full_name}",
            amount_cents=recurring_amount,
            due_on=payload.first_due_on,
            issued_on=payload.started_on,
        )

        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.CREATE,
            entity_type="Subscription",
            entity_id=row.id,
            summary=f"Assinatura criada para '{member.full_name}'.",
            details={
                "member_id": str(member.id),
                "membership_plan_id": str(plan.id),
                "started_on": payload.started_on.isoformat(),
                "first_due_on": payload.first_due_on.isoformat(),
                "price_override_cents": payload.price_override_cents,
            },
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def set_subscription_status(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        subscription_id: UUID,
        status: SubscriptionStatus,
        request_id: str | None = None,
    ) -> Subscription:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        row = self._get_subscription(business_id=business_id, subscription_id=subscription_id)
        if row.status == status:
            return row
        if status == SubscriptionStatus.ACTIVE:
            member = self._get_member(business_id=business_id, member_id=row.member_id)
            if member.status != MemberStatus.ACTIVE:
                raise ValueError("O associado precisa estar ativo para reativar a assinatura.")
            row.canceled_on = None
        if status == SubscriptionStatus.CANCELED:
            row.canceled_on = date.today()
        previous_status = row.status
        row.status = status
        self.db.add(row)
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.UPDATE,
            entity_type="Subscription",
            entity_id=row.id,
            summary=f"Assinatura alterada para {status.value}.",
            details={"before": previous_status.value, "after": status.value},
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def generate_next_receivable(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        subscription_id: UUID,
        request_id: str | None = None,
    ) -> Receivable:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        subscription = self._get_subscription(business_id=business_id, subscription_id=subscription_id)
        if subscription.status != SubscriptionStatus.ACTIVE:
            raise ValueError("Apenas assinaturas ativas podem gerar novas cobrancas.")
        plan = self._get_membership_plan(business_id=business_id, plan_id=subscription.membership_plan_id)
        member = self._get_member(business_id=business_id, member_id=subscription.member_id)
        row = self._create_receivable_row(
            business_id=business_id,
            member_id=member.id,
            subscription_id=subscription.id,
            kind=ReceivableKind.RECURRING,
            description=f"Mensalidade {plan.name} - {member.full_name}",
            amount_cents=self._subscription_amount_cents(subscription),
            due_on=subscription.next_billing_on,
            issued_on=date.today(),
        )
        subscription.next_billing_on = self._add_months_with_day(subscription.next_billing_on, 1, plan.billing_day)
        self.db.add(subscription)
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.CREATE,
            entity_type="Receivable",
            entity_id=row.id,
            summary=f"Nova cobranca gerada para '{member.full_name}'.",
            details={"subscription_id": str(subscription.id), "due_on": row.due_on.isoformat()},
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_receivables(self, *, owner_user_id: UUID, business_id: UUID) -> list[Receivable]:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        self._refresh_overdue_receivables(business_id=business_id)
        return list(
            self.db.scalars(
                select(Receivable)
                .where(Receivable.business_id == business_id)
                .order_by(Receivable.due_on.asc(), Receivable.created_at.desc())
            )
        )

    def record_receipt(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        receivable_id: UUID,
        payload: RecordReceiptDTO,
        request_id: str | None = None,
    ) -> Receipt:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        receivable = self._get_receivable(business_id=business_id, receivable_id=receivable_id)
        if receivable.status in {
            ReceivableStatus.CANCELED,
            ReceivableStatus.REFUNDED,
            ReceivableStatus.RENEGOTIATED,
        }:
            raise ValueError("Este titulo nao aceita novos recebimentos.")

        current_received = self._receivable_received_cents(receivable)
        due_total = self._receivable_due_total(receivable)
        if current_received + payload.amount_received_cents > due_total:
            raise ValueError("O recebimento excede o saldo do titulo.")

        row = Receipt(
            business_id=business_id,
            receivable_id=receivable.id,
            received_on=payload.received_on,
            amount_received_cents=payload.amount_received_cents,
            method=payload.method,
            note=payload.note,
        )
        self.db.add(row)
        self.db.flush()

        new_total = current_received + payload.amount_received_cents
        receivable.paid_on = payload.received_on if new_total >= due_total else None
        receivable.status = (
            ReceivableStatus.PAID
            if new_total >= due_total
            else self._open_receivable_status(receivable.due_on, payload.received_on)
        )
        self.db.add(receivable)
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.CREATE,
            entity_type="Receipt",
            entity_id=row.id,
            summary=f"Recebimento registrado para '{receivable.description}'.",
            details=payload.model_dump(mode="json"),
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def _ensure_soomei_membership_plans(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        request_id: str | None,
    ) -> None:
        existing = {
            item.name
            for item in self.list_membership_plans(owner_user_id=actor_user_id, business_id=business_id)
        }
        for template in SOOMEI_MEMBERSHIP_PLANS:
            if template["name"] in existing:
                continue
            self.create_membership_plan(
                actor_user_id=actor_user_id,
                business_id=business_id,
                payload=UpsertMembershipPlanDTO(**template),
                request_id=request_id,
            )

    def _refresh_overdue_receivables(self, *, business_id: UUID) -> None:
        today = date.today()
        rows = list(
            self.db.scalars(
                select(Receivable).where(
                    Receivable.business_id == business_id,
                    Receivable.status.in_(
                        [
                            ReceivableStatus.PLANNED,
                            ReceivableStatus.ISSUED,
                            ReceivableStatus.OVERDUE,
                        ]
                    ),
                )
            )
        )
        changed = False
        for row in rows:
            next_status = self._open_receivable_status(row.due_on, today)
            if row.status != next_status:
                row.status = next_status
                self.db.add(row)
                changed = True
        if changed:
            self.db.commit()

    def _cascade_member_status_to_subscriptions(
        self,
        *,
        actor_user_id: UUID,
        member: Member,
        request_id: str | None,
    ) -> None:
        target_status = {
            MemberStatus.SUSPENDED: SubscriptionStatus.SUSPENDED,
            MemberStatus.BLOCKED: SubscriptionStatus.BLOCKED,
            MemberStatus.CANCELED: SubscriptionStatus.CANCELED,
        }[member.status]
        rows = list(
            self.db.scalars(
                select(Subscription).where(
                    Subscription.business_id == member.business_id,
                    Subscription.member_id == member.id,
                    Subscription.status != SubscriptionStatus.CANCELED,
                )
            )
        )
        for row in rows:
            previous_status = row.status
            row.status = target_status
            if target_status == SubscriptionStatus.CANCELED:
                row.canceled_on = date.today()
            self.db.add(row)
            self._add_audit(
                business_id=member.business_id,
                actor_user_id=actor_user_id,
                action=AuditAction.UPDATE,
                entity_type="Subscription",
                entity_id=row.id,
                summary=f"Assinatura de '{member.full_name}' ajustada por mudanca de status do associado.",
                details={"before": previous_status.value, "after": row.status.value},
                request_id=request_id,
            )

    def _create_receivable_row(
        self,
        *,
        business_id: UUID,
        member_id: UUID,
        subscription_id: UUID | None,
        kind: ReceivableKind,
        description: str,
        amount_cents: int,
        due_on: date,
        issued_on: date,
    ) -> Receivable:
        competency_month = Month.from_any_date(due_on).value
        existing = None
        if subscription_id is not None:
            existing = self.db.scalar(
                select(Receivable).where(
                    Receivable.subscription_id == subscription_id,
                    Receivable.kind == kind,
                    Receivable.competency_month == competency_month,
                )
            )
        if existing is not None:
            raise ValueError("Ja existe cobranca emitida para esta competencia.")
        row = Receivable(
            business_id=business_id,
            member_id=member_id,
            subscription_id=subscription_id,
            kind=kind,
            status=self._open_receivable_status(due_on, issued_on),
            description=description,
            amount_cents=amount_cents,
            discount_cents=0,
            due_on=due_on,
            issued_on=issued_on,
            paid_on=None,
            competency_month=competency_month,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _assert_membership_plan_available(
        self,
        *,
        business_id: UUID,
        name: str,
        external_product_id: str | None = None,
        external_reference_id: str | None = None,
        exclude_id: UUID | None = None,
    ) -> None:
        stmt = select(MembershipPlan).where(
            MembershipPlan.business_id == business_id,
            func.lower(MembershipPlan.name) == name.lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(MembershipPlan.id != exclude_id)
        if self.db.scalar(stmt) is not None:
            raise ValueError("Ja existe um plano com este nome.")
        if external_product_id:
            product_stmt = select(MembershipPlan).where(
                MembershipPlan.business_id == business_id,
                func.lower(MembershipPlan.external_product_id) == external_product_id.lower(),
            )
            if exclude_id is not None:
                product_stmt = product_stmt.where(MembershipPlan.id != exclude_id)
            if self.db.scalar(product_stmt) is not None:
                raise ValueError("Ja existe um plano mapeado para este product_id externo.")
        if external_reference_id:
            reference_stmt = select(MembershipPlan).where(
                MembershipPlan.business_id == business_id,
                func.lower(MembershipPlan.external_reference_id) == external_reference_id.lower(),
            )
            if exclude_id is not None:
                reference_stmt = reference_stmt.where(MembershipPlan.id != exclude_id)
            if self.db.scalar(reference_stmt) is not None:
                raise ValueError("Ja existe um plano mapeado para este reference_id externo.")

    def _get_member(self, *, business_id: UUID, member_id: UUID) -> Member:
        row = self.db.scalar(
            select(Member).where(
                Member.business_id == business_id,
                Member.id == member_id,
            )
        )
        if row is None:
            raise ValueError("Associado nao encontrado.")
        return row

    def _get_membership_plan(self, *, business_id: UUID, plan_id: UUID) -> MembershipPlan:
        row = self.db.scalar(
            select(MembershipPlan).where(
                MembershipPlan.business_id == business_id,
                MembershipPlan.id == plan_id,
            )
        )
        if row is None:
            raise ValueError("Plano nao encontrado.")
        return row

    def _get_subscription(self, *, business_id: UUID, subscription_id: UUID) -> Subscription:
        row = self.db.scalar(
            select(Subscription).where(
                Subscription.business_id == business_id,
                Subscription.id == subscription_id,
            )
        )
        if row is None:
            raise ValueError("Assinatura nao encontrada.")
        return row

    def _get_receivable(self, *, business_id: UUID, receivable_id: UUID) -> Receivable:
        row = self.db.scalar(
            select(Receivable).where(
                Receivable.business_id == business_id,
                Receivable.id == receivable_id,
            )
        )
        if row is None:
            raise ValueError("Titulo a receber nao encontrado.")
        return row

    def _subscription_amount_cents(self, row: Subscription) -> int:
        return row.price_override_cents or row.membership_plan.recurring_amount_cents

    @staticmethod
    def _build_subscription_row(
        *,
        business_id: UUID,
        member_id: UUID,
        membership_plan_id: UUID,
        started_on: date,
        next_billing_on: date,
        price_override_cents: int | None,
        notes: str | None,
        external_subscription_id: str | None = None,
    ) -> Subscription:
        return Subscription(
            business_id=business_id,
            member_id=member_id,
            membership_plan_id=membership_plan_id,
            status=SubscriptionStatus.ACTIVE,
            started_on=started_on,
            next_billing_on=next_billing_on,
            external_subscription_id=external_subscription_id,
            price_override_cents=price_override_cents,
            cancel_requested_at=None,
            canceled_on=None,
            notes=notes,
        )

    @staticmethod
    def _receivable_due_total(row: Receivable) -> int:
        return row.amount_cents - row.discount_cents

    def _receivable_received_cents(self, row: Receivable) -> int:
        return int(
            self.db.scalar(
                select(func.coalesce(func.sum(Receipt.amount_received_cents), 0)).where(
                    Receipt.receivable_id == row.id
                )
            )
            or 0
        )

    def _receivable_balance_cents(self, row: Receivable) -> int:
        return max(self._receivable_due_total(row) - self._receivable_received_cents(row), 0)

    @staticmethod
    def _open_receivable_status(due_on: date, reference: date) -> ReceivableStatus:
        return ReceivableStatus.OVERDUE if due_on < reference else ReceivableStatus.ISSUED

    @staticmethod
    def _add_months_with_day(value: date, months: int, day: int) -> date:
        target_month = Month.from_any_date(value).add_months(months).value
        last_day = calendar.monthrange(target_month.year, target_month.month)[1]
        return date(target_month.year, target_month.month, min(day, last_day))

    @staticmethod
    def _format_brl(cents: int) -> str:
        amount = Decimal(cents) / Decimal("100")
        text = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {text}"
