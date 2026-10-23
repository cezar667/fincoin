from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.application.dto.business_control_dto import (
    CreateBusinessCashEntryDTO,
    CreateBusinessFundingDTO,
    PayBusinessFundingInstallmentDTO,
    RecordReceiptDTO,
)
from app.application.use_cases.business_control_phase2 import (
    BusinessOperationsDashboardSummary,
    JourneyStage,
    MindMapNode,
)
from app.application.use_cases.themembers_integration import TheMembersIntegrationService
from app.domain.value_objects.month import Month
from app.infrastructure.db.models.business_account import BusinessAccount
from app.infrastructure.db.models.business_cash_entry import BusinessCashEntry
from app.infrastructure.db.models.business_category import BusinessCategory
from app.infrastructure.db.models.business_funding import BusinessFunding
from app.infrastructure.db.models.business_funding_installment import BusinessFundingInstallment
from app.infrastructure.db.models.cost_center import CostCenter
from app.infrastructure.db.models.enums import (
    AuditAction,
    BusinessAccountType,
    BusinessCashActivityType,
    BusinessCategoryKind,
    FundingInstallmentStatus,
    ReceiptMethod,
    ReceivableKind,
    ReceivableStatus,
    TransactionDirection,
)
from app.infrastructure.db.models.member import Member
from app.infrastructure.db.models.receipt import Receipt
from app.infrastructure.db.models.receivable import Receivable
from app.infrastructure.db.models.subscription import Subscription


@dataclass(slots=True)
class CashJourneyStage:
    title: str
    metric_text: str
    caption: str
    tone: str


@dataclass(slots=True)
class CashBreakdownItem:
    title: str
    caption: str
    amount_cents: int
    share_percent: int


@dataclass(slots=True)
class AccountCashPosition:
    account: BusinessAccount
    current_balance_cents: int
    net_movement_cents: int


@dataclass(slots=True)
class FundingSnapshot:
    funding: BusinessFunding
    paid_cents: int
    outstanding_cents: int
    linked_outflow_cents: int
    preserved_credit_cents: int
    next_installment: BusinessFundingInstallment | None


@dataclass(slots=True)
class DailyGrowthPoint:
    reference_date: date
    label: str
    new_members_count: int
    new_subscriptions_count: int
    paid_orders_count: int
    revenue_cents: int


@dataclass(slots=True)
class BusinessFinanceDashboardSummary(BusinessOperationsDashboardSummary):
    current_cash_cents: int
    inflows_this_month_cents: int
    outflows_this_month_cents: int
    net_cash_this_month_cents: int
    total_financing_cents: int
    financing_paid_cents: int
    financing_open_balance_cents: int
    financing_due_next_30_days_cents: int
    capital_consumed_cents: int
    capital_preserved_cents: int
    revenue_today_cents: int
    revenue_last_7_days_cents: int
    new_members_today: int
    new_subscriptions_today: int
    one_time_sales_this_month_cents: int
    recent_cash_entries: list[BusinessCashEntry]
    account_positions: list[AccountCashPosition]
    top_spending_categories: list[CashBreakdownItem]
    top_spending_cost_centers: list[CashBreakdownItem]
    cash_journey_stages: list[CashJourneyStage]
    capital_map_nodes: list[MindMapNode]
    funding_snapshots: list[FundingSnapshot]
    upcoming_installments: list[BusinessFundingInstallment]
    daily_growth_points: list[DailyGrowthPoint]


class BusinessControlFinanceService(TheMembersIntegrationService):
    def build_dashboard(self, *, owner_user_id: UUID, business_id: UUID) -> BusinessFinanceDashboardSummary:
        base = super().build_dashboard(owner_user_id=owner_user_id, business_id=business_id)
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        self._refresh_overdue_funding_installments(business_id=business_id)

        today = date.today()
        current_month = Month.from_any_date(today).value
        next_month = Month.from_any_date(today).add_months(1).value
        due_limit = today + timedelta(days=30)

        accounts = self.list_accounts(owner_user_id=owner_user_id, business_id=business_id)
        cash_entries = self._list_cash_entries_for_business(business_id=business_id)
        installments = self._list_funding_installments_for_business(business_id=business_id)
        funding_rows = self._list_fundings_for_business(business_id=business_id)
        growth_points = self._build_daily_growth_points(business_id=business_id, reference=today, days=14)

        current_cash_cents = self._current_cash_cents(accounts=accounts, entries=cash_entries)
        inflows_this_month_cents = sum(
            item.amount_cents
            for item in cash_entries
            if item.direction == TransactionDirection.INCOME
            and current_month <= item.occurred_on < next_month
        )
        outflows_this_month_cents = sum(
            item.amount_cents
            for item in cash_entries
            if item.direction == TransactionDirection.EXPENSE
            and current_month <= item.occurred_on < next_month
        )
        net_cash_this_month_cents = inflows_this_month_cents - outflows_this_month_cents

        total_financing_cents = sum(item.principal_cents for item in funding_rows)
        financing_paid_cents = sum(item.amount_paid_cents for item in installments if item.status == FundingInstallmentStatus.PAID)
        financing_open_balance_cents = sum(
            self._installment_balance_cents(item)
            for item in installments
            if item.status != FundingInstallmentStatus.PAID
        )
        financing_due_next_30_days_cents = sum(
            self._installment_balance_cents(item)
            for item in installments
            if item.status != FundingInstallmentStatus.PAID and today <= item.due_on <= due_limit
        )

        capital_preserved_cents = min(max(current_cash_cents, 0), total_financing_cents)
        capital_consumed_cents = max(total_financing_cents - capital_preserved_cents, 0)
        revenue_today_cents = growth_points[-1].revenue_cents if growth_points else 0
        revenue_last_7_days_cents = sum(item.revenue_cents for item in growth_points[-7:])
        new_members_today = growth_points[-1].new_members_count if growth_points else 0
        new_subscriptions_today = growth_points[-1].new_subscriptions_count if growth_points else 0
        one_time_sales_this_month_cents = int(
            self.db.scalar(
                select(func.coalesce(func.sum(Receipt.amount_received_cents), 0))
                .join(Receivable, Receipt.receivable_id == Receivable.id)
                .where(
                    Receipt.business_id == business_id,
                    Receipt.received_on >= current_month,
                    Receipt.received_on < next_month,
                    Receivable.subscription_id.is_(None),
                )
            )
            or 0
        )
        account_positions = self.build_account_positions(
            owner_user_id=owner_user_id,
            business_id=business_id,
            accounts=accounts,
            cash_entries=cash_entries,
        )
        top_spending_categories = self.build_spending_breakdown(
            owner_user_id=owner_user_id,
            business_id=business_id,
            dimension="category",
            cash_entries=cash_entries,
        )
        top_spending_cost_centers = self.build_spending_breakdown(
            owner_user_id=owner_user_id,
            business_id=business_id,
            dimension="cost_center",
            cash_entries=cash_entries,
        )
        funding_snapshots = self.list_funding_snapshots(
            owner_user_id=owner_user_id,
            business_id=business_id,
            funding_rows=funding_rows,
            installments=installments,
            cash_entries=cash_entries,
        )

        cash_journey_stages = [
            CashJourneyStage("Captacao", self._format_brl(total_financing_cents), "Capital levantado para acelerar a Soomei.", "sky"),
            CashJourneyStage(
                "Uso do capital",
                self._format_brl(sum(item.linked_outflow_cents for item in funding_snapshots)),
                "Saidas vinculadas diretamente aos creditos cadastrados.",
                "amber",
            ),
            CashJourneyStage("Operacao do mes", self._format_brl(outflows_this_month_cents), "Consumo do caixa no ciclo corrente.", "rose"),
            CashJourneyStage("Entradas do mes", self._format_brl(inflows_this_month_cents), "Receitas, aportes e captacoes no periodo.", "emerald"),
            CashJourneyStage(
                "Parcelas 30 dias",
                self._format_brl(financing_due_next_30_days_cents),
                "Compromissos que ja pressionam o proximo giro.",
                "indigo",
            ),
            CashJourneyStage("Reserva", self._format_brl(capital_preserved_cents), "Parcela do credito que ainda esta preservada em caixa.", "teal"),
        ]

        leader_category = top_spending_categories[0] if top_spending_categories else None
        leader_cost_center = top_spending_cost_centers[0] if top_spending_cost_centers else None
        capital_map_nodes = [
            MindMapNode("Caixa atual", self._format_brl(current_cash_cents), "Saldo vivo das contas empresariais.", "teal"),
            MindMapNode("Entradas do mes", self._format_brl(inflows_this_month_cents), "Tudo o que efetivamente entrou em caixa.", "emerald"),
            MindMapNode("Saidas do mes", self._format_brl(outflows_this_month_cents), "Consumo operacional, investimentos e financiamento.", "rose"),
            MindMapNode("Divida em aberto", self._format_brl(financing_open_balance_cents), "Parcelas ainda nao quitadas.", "indigo"),
            MindMapNode(
                "Maior categoria",
                self._format_brl(leader_category.amount_cents) if leader_category else "R$ 0,00",
                leader_category.title if leader_category else "Nenhum gasto categorizado.",
                "amber",
            ),
            MindMapNode(
                "Centro lider",
                self._format_brl(leader_cost_center.amount_cents) if leader_cost_center else "R$ 0,00",
                leader_cost_center.title if leader_cost_center else "Nenhum centro de custo usado.",
                "sky",
            ),
        ]

        return BusinessFinanceDashboardSummary(
            total_businesses=base.total_businesses,
            active_businesses=base.active_businesses,
            active_accounts=base.active_accounts,
            active_categories=base.active_categories,
            active_cost_centers=base.active_cost_centers,
            initial_balance_cents=base.initial_balance_cents,
            recent_audits=base.recent_audits,
            total_members=base.total_members,
            active_members=base.active_members,
            active_plans=base.active_plans,
            total_subscriptions=base.total_subscriptions,
            active_subscriptions=base.active_subscriptions,
            mrr_gross_cents=base.mrr_gross_cents,
            expected_this_month_cents=base.expected_this_month_cents,
            received_this_month_cents=base.received_this_month_cents,
            overdue_cents=base.overdue_cents,
            overdue_count=base.overdue_count,
            open_receivables_count=base.open_receivables_count,
            recent_receivables=base.recent_receivables,
            journey_stages=base.journey_stages,
            mind_map_nodes=base.mind_map_nodes,
            current_cash_cents=current_cash_cents,
            inflows_this_month_cents=inflows_this_month_cents,
            outflows_this_month_cents=outflows_this_month_cents,
            net_cash_this_month_cents=net_cash_this_month_cents,
            total_financing_cents=total_financing_cents,
            financing_paid_cents=financing_paid_cents,
            financing_open_balance_cents=financing_open_balance_cents,
            financing_due_next_30_days_cents=financing_due_next_30_days_cents,
            capital_consumed_cents=capital_consumed_cents,
            capital_preserved_cents=capital_preserved_cents,
            revenue_today_cents=revenue_today_cents,
            revenue_last_7_days_cents=revenue_last_7_days_cents,
            new_members_today=new_members_today,
            new_subscriptions_today=new_subscriptions_today,
            one_time_sales_this_month_cents=one_time_sales_this_month_cents,
            recent_cash_entries=cash_entries[:8],
            account_positions=account_positions,
            top_spending_categories=top_spending_categories,
            top_spending_cost_centers=top_spending_cost_centers,
            cash_journey_stages=cash_journey_stages,
            capital_map_nodes=capital_map_nodes,
            funding_snapshots=funding_snapshots[:4],
            upcoming_installments=[item for item in installments if item.status != FundingInstallmentStatus.PAID][:6],
            daily_growth_points=growth_points,
        )

    def list_cash_entries(
        self,
        *,
        owner_user_id: UUID,
        business_id: UUID,
        limit: int | None = 60,
    ) -> list[BusinessCashEntry]:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        return self._list_cash_entries_for_business(business_id=business_id, limit=limit)

    def list_fundings(
        self,
        *,
        owner_user_id: UUID,
        business_id: UUID,
    ) -> list[BusinessFunding]:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        return self._list_fundings_for_business(business_id=business_id)

    def list_funding_installments(
        self,
        *,
        owner_user_id: UUID,
        business_id: UUID,
        limit: int | None = None,
        include_paid: bool = True,
    ) -> list[BusinessFundingInstallment]:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        self._refresh_overdue_funding_installments(business_id=business_id)
        rows = self._list_funding_installments_for_business(business_id=business_id, limit=limit)
        if include_paid:
            return rows
        return [item for item in rows if item.status != FundingInstallmentStatus.PAID]

    def build_account_positions(
        self,
        *,
        owner_user_id: UUID,
        business_id: UUID,
        accounts: list[BusinessAccount] | None = None,
        cash_entries: list[BusinessCashEntry] | None = None,
    ) -> list[AccountCashPosition]:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        account_rows = accounts or self.list_accounts(owner_user_id=owner_user_id, business_id=business_id)
        entry_rows = cash_entries or self._list_cash_entries_for_business(business_id=business_id)
        net_by_account: dict[UUID, int] = {item.id: 0 for item in account_rows}
        for entry in entry_rows:
            net_by_account[entry.business_account_id] = net_by_account.get(entry.business_account_id, 0) + self._signed_amount(entry)
        positions = [
            AccountCashPosition(
                account=item,
                current_balance_cents=item.initial_balance_cents + net_by_account.get(item.id, 0),
                net_movement_cents=net_by_account.get(item.id, 0),
            )
            for item in account_rows
        ]
        return sorted(
            positions,
            key=lambda item: (
                not item.account.is_active,
                -item.current_balance_cents,
                item.account.name.lower(),
            ),
        )

    def build_spending_breakdown(
        self,
        *,
        owner_user_id: UUID,
        business_id: UUID,
        dimension: str,
        cash_entries: list[BusinessCashEntry] | None = None,
    ) -> list[CashBreakdownItem]:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        entry_rows = cash_entries or self._list_cash_entries_for_business(business_id=business_id)
        buckets: dict[str, int] = {}
        for entry in entry_rows:
            if entry.direction != TransactionDirection.EXPENSE:
                continue
            if dimension == "category":
                title = entry.category.name if entry.category else "Sem categoria"
                caption = "Distribuicao das saidas por categoria."
            else:
                title = entry.cost_center.name if entry.cost_center else "Sem centro de custo"
                caption = "Distribuicao das saidas por centro de custo."
            buckets[title] = buckets.get(title, 0) + entry.amount_cents

        total = sum(buckets.values())
        rows: list[CashBreakdownItem] = []
        for title, amount_cents in sorted(buckets.items(), key=lambda item: (-item[1], item[0].lower()))[:5]:
            share_percent = int(round((amount_cents / total) * 100)) if total else 0
            rows.append(
                CashBreakdownItem(
                    title=title,
                    caption=caption,
                    amount_cents=amount_cents,
                    share_percent=share_percent,
                )
            )
        return rows

    def list_funding_snapshots(
        self,
        *,
        owner_user_id: UUID,
        business_id: UUID,
        funding_rows: list[BusinessFunding] | None = None,
        installments: list[BusinessFundingInstallment] | None = None,
        cash_entries: list[BusinessCashEntry] | None = None,
    ) -> list[FundingSnapshot]:
        self.get_business(owner_user_id=owner_user_id, business_id=business_id)
        fundings = funding_rows or self._list_fundings_for_business(business_id=business_id)
        installment_rows = installments or self._list_funding_installments_for_business(business_id=business_id)
        entry_rows = cash_entries or self._list_cash_entries_for_business(business_id=business_id)

        installments_by_funding: dict[UUID, list[BusinessFundingInstallment]] = {}
        for item in installment_rows:
            installments_by_funding.setdefault(item.funding_id, []).append(item)

        outflows_by_funding: dict[UUID, int] = {}
        for entry in entry_rows:
            if entry.funding_id is None or entry.direction != TransactionDirection.EXPENSE:
                continue
            outflows_by_funding[entry.funding_id] = outflows_by_funding.get(entry.funding_id, 0) + entry.amount_cents

        snapshots: list[FundingSnapshot] = []
        for funding in fundings:
            rows = installments_by_funding.get(funding.id, [])
            next_installment = next((item for item in rows if item.status != FundingInstallmentStatus.PAID), None)
            paid_cents = sum(item.amount_paid_cents for item in rows if item.status == FundingInstallmentStatus.PAID)
            outstanding_cents = sum(
                self._installment_balance_cents(item)
                for item in rows
                if item.status != FundingInstallmentStatus.PAID
            )
            linked_outflow_cents = outflows_by_funding.get(funding.id, 0)
            snapshots.append(
                FundingSnapshot(
                    funding=funding,
                    paid_cents=paid_cents,
                    outstanding_cents=outstanding_cents,
                    linked_outflow_cents=linked_outflow_cents,
                    preserved_credit_cents=max(funding.principal_cents - linked_outflow_cents, 0),
                    next_installment=next_installment,
                )
            )
        return snapshots

    def create_cash_entry(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        payload: CreateBusinessCashEntryDTO,
        request_id: str | None = None,
    ) -> BusinessCashEntry:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        account = self._get_account(business_id=business_id, account_id=payload.business_account_id)
        category = self._get_category(business_id=business_id, category_id=payload.business_category_id) if payload.business_category_id else None
        cost_center = self._get_cost_center(business_id=business_id, cost_center_id=payload.cost_center_id) if payload.cost_center_id else None
        funding = self._get_funding(business_id=business_id, funding_id=payload.funding_id) if payload.funding_id else None
        self._assert_active_account(account)
        if category is not None:
            self._assert_active_category(category)
        if cost_center is not None:
            self._assert_active_cost_center(cost_center)

        row = self._create_cash_entry_row(
            business_id=business_id,
            account_id=account.id,
            category_id=category.id if category is not None else None,
            cost_center_id=cost_center.id if cost_center is not None else None,
            funding_id=funding.id if funding is not None else None,
            activity_type=payload.activity_type,
            direction=payload.direction,
            description=payload.description,
            amount_cents=payload.amount_cents,
            occurred_on=payload.occurred_on,
            notes=payload.notes,
        )
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.CREATE,
            entity_type="BusinessCashEntry",
            entity_id=row.id,
            summary=f"Lancamento de caixa '{row.description}' registrado.",
            details=payload.model_dump(mode="json"),
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def create_funding(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        payload: CreateBusinessFundingDTO,
        request_id: str | None = None,
    ) -> BusinessFunding:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        if payload.first_due_on < payload.disbursed_on:
            raise ValueError("A primeira parcela nao pode vencer antes do desembolso.")
        if payload.installment_amount_cents * payload.installment_count < payload.principal_cents:
            raise ValueError("O total das parcelas precisa cobrir o principal captado.")

        disbursement_account = self._get_account(business_id=business_id, account_id=payload.disbursement_account_id)
        settlement_account = self._get_account(business_id=business_id, account_id=payload.settlement_account_id)
        payment_category = (
            self._get_category(business_id=business_id, category_id=payload.payment_category_id)
            if payload.payment_category_id
            else None
        )
        cost_center = (
            self._get_cost_center(business_id=business_id, cost_center_id=payload.cost_center_id)
            if payload.cost_center_id
            else None
        )
        self._assert_active_account(disbursement_account)
        self._assert_active_account(settlement_account)
        if payment_category is not None:
            self._assert_active_category(payment_category)
        if cost_center is not None:
            self._assert_active_cost_center(cost_center)

        row = BusinessFunding(
            business_id=business_id,
            disbursement_account_id=disbursement_account.id,
            settlement_account_id=settlement_account.id,
            payment_category_id=payment_category.id if payment_category is not None else None,
            cost_center_id=cost_center.id if cost_center is not None else None,
            name=payload.name,
            lender_name=payload.lender_name,
            principal_cents=payload.principal_cents,
            installment_amount_cents=payload.installment_amount_cents,
            installment_count=payload.installment_count,
            annual_interest_bps=payload.annual_interest_bps,
            disbursed_on=payload.disbursed_on,
            first_due_on=payload.first_due_on,
            notes=payload.notes,
        )
        self.db.add(row)
        self.db.flush()

        self._create_cash_entry_row(
            business_id=business_id,
            account_id=disbursement_account.id,
            category_id=None,
            cost_center_id=cost_center.id if cost_center is not None else None,
            funding_id=row.id,
            activity_type=BusinessCashActivityType.FINANCING,
            direction=TransactionDirection.INCOME,
            description=f"Credito captado: {row.name}",
            amount_cents=row.principal_cents,
            occurred_on=row.disbursed_on,
            notes=row.notes or row.lender_name,
        )

        due_day = payload.first_due_on.day
        for offset in range(payload.installment_count):
            due_on = self._add_months_with_day(payload.first_due_on, offset, due_day)
            self.db.add(
                BusinessFundingInstallment(
                    funding_id=row.id,
                    business_id=business_id,
                    installment_number=offset + 1,
                    due_on=due_on,
                    amount_due_cents=payload.installment_amount_cents,
                    amount_paid_cents=0,
                    paid_on=None,
                    status=self._open_installment_status(due_on=due_on, reference=date.today()),
                )
            )

        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.CREATE,
            entity_type="BusinessFunding",
            entity_id=row.id,
            summary=f"Financiamento '{row.name}' cadastrado.",
            details=payload.model_dump(mode="json"),
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

    def pay_funding_installment(
        self,
        *,
        actor_user_id: UUID,
        business_id: UUID,
        installment_id: UUID,
        payload: PayBusinessFundingInstallmentDTO,
        request_id: str | None = None,
    ) -> BusinessFundingInstallment:
        self.get_business(owner_user_id=actor_user_id, business_id=business_id)
        row = self._get_funding_installment(business_id=business_id, installment_id=installment_id)
        if row.status == FundingInstallmentStatus.PAID:
            raise ValueError("Esta parcela ja foi quitada.")
        balance_cents = self._installment_balance_cents(row)
        if payload.amount_paid_cents != balance_cents:
            raise ValueError("A baixa manual precisa quitar o saldo integral da parcela.")

        funding = row.funding
        settlement_account = funding.settlement_account
        self._assert_active_account(settlement_account)

        cash_entry = self._create_cash_entry_row(
            business_id=business_id,
            account_id=settlement_account.id,
            category_id=funding.payment_category_id,
            cost_center_id=funding.cost_center_id,
            funding_id=funding.id,
            activity_type=BusinessCashActivityType.FINANCING,
            direction=TransactionDirection.EXPENSE,
            description=f"Parcela {row.installment_number}/{funding.installment_count} - {funding.name}",
            amount_cents=payload.amount_paid_cents,
            occurred_on=payload.paid_on,
            notes=payload.notes or funding.notes,
        )
        row.amount_paid_cents = payload.amount_paid_cents
        row.paid_on = payload.paid_on
        row.status = FundingInstallmentStatus.PAID
        row.payment_entry_id = cash_entry.id
        self.db.add(row)
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.UPDATE,
            entity_type="BusinessFundingInstallment",
            entity_id=row.id,
            summary=f"Parcela {row.installment_number} de '{funding.name}' quitada.",
            details=payload.model_dump(mode="json"),
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(row)
        return row

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

        self._resolve_receipt_account(business_id=business_id)
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
        self._sync_receipt_to_cash_entry(
            business_id=business_id,
            receipt=row,
            receivable=receivable,
            actor_user_id=actor_user_id,
            request_id=request_id,
        )
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

    def _record_external_receipt(
        self,
        *,
        business_id: UUID,
        receivable: Receivable,
        transaction: dict[str, object],
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

        self._resolve_receipt_account(business_id=business_id)
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
        self._sync_receipt_to_cash_entry(
            business_id=business_id,
            receipt=row,
            receivable=receivable,
            actor_user_id=None,
            request_id=None,
        )
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

    def _sync_receipt_to_cash_entry(
        self,
        *,
        business_id: UUID,
        receipt: Receipt,
        receivable: Receivable,
        actor_user_id: UUID | None,
        request_id: str | None,
    ) -> BusinessCashEntry:
        account = self._resolve_receipt_account(business_id=business_id)
        category = self._resolve_receivable_cash_category(business_id=business_id, receivable=receivable)
        row = self._create_cash_entry_row(
            business_id=business_id,
            account_id=account.id,
            category_id=category.id if category is not None else None,
            cost_center_id=None,
            funding_id=None,
            activity_type=BusinessCashActivityType.OPERATING,
            direction=TransactionDirection.INCOME,
            description=f"Recebimento: {receivable.description}",
            amount_cents=receipt.amount_received_cents,
            occurred_on=receipt.received_on,
            notes=receipt.note or self._receipt_note_label(receipt.method),
        )
        self._add_audit(
            business_id=business_id,
            actor_user_id=actor_user_id,
            action=AuditAction.CREATE,
            entity_type="BusinessCashEntry",
            entity_id=row.id,
            summary=f"Entrada de caixa reconhecida para '{receivable.description}'.",
            details={
                "receipt_id": str(receipt.id),
                "method": receipt.method.value,
                "amount_received_cents": receipt.amount_received_cents,
            },
            request_id=request_id,
        )
        return row

    def _resolve_receipt_account(self, *, business_id: UUID) -> BusinessAccount:
        accounts = [item for item in self._list_accounts_for_business(business_id=business_id) if item.is_active]
        if not accounts:
            raise ValueError("Cadastre ao menos uma conta empresarial ativa para reconhecer recebimentos em caixa.")
        ordered = sorted(
            accounts,
            key=lambda item: (
                0 if item.type == BusinessAccountType.RECEIVABLE else 1 if item.type == BusinessAccountType.BANK else 2,
                item.name.lower(),
            ),
        )
        return ordered[0]

    def _resolve_receivable_cash_category(
        self,
        *,
        business_id: UUID,
        receivable: Receivable,
    ) -> BusinessCategory | None:
        if receivable.subscription_id is None:
            product_category = self.db.scalar(
                select(BusinessCategory).where(
                    BusinessCategory.business_id == business_id,
                    BusinessCategory.code == "PRD",
                    BusinessCategory.is_active.is_(True),
                )
            )
            if product_category is not None:
                return product_category
        code_map = {
            ReceivableKind.RECURRING: "MRR",
            ReceivableKind.ACTIVATION: "ATV",
            ReceivableKind.REPLACEMENT: "2VIA",
        }
        target_code = code_map.get(receivable.kind)
        if target_code:
            row = self.db.scalar(
                select(BusinessCategory).where(
                    BusinessCategory.business_id == business_id,
                    BusinessCategory.code == target_code,
                    BusinessCategory.is_active.is_(True),
                )
            )
            if row is not None:
                return row

        target_kind = (
            BusinessCategoryKind.RECURRING_REVENUE
            if receivable.kind == ReceivableKind.RECURRING
            else BusinessCategoryKind.NON_RECURRING_REVENUE
        )
        return self.db.scalar(
            select(BusinessCategory).where(
                BusinessCategory.business_id == business_id,
                BusinessCategory.kind == target_kind,
                BusinessCategory.is_active.is_(True),
            )
        )

    def _list_accounts_for_business(self, *, business_id: UUID) -> list[BusinessAccount]:
        return list(
            self.db.scalars(
                select(BusinessAccount)
                .where(BusinessAccount.business_id == business_id)
                .order_by(BusinessAccount.is_active.desc(), BusinessAccount.name.asc())
            )
        )

    def _list_cash_entries_for_business(
        self,
        *,
        business_id: UUID,
        limit: int | None = None,
    ) -> list[BusinessCashEntry]:
        stmt = (
            select(BusinessCashEntry)
            .options(
                selectinload(BusinessCashEntry.account),
                selectinload(BusinessCashEntry.category),
                selectinload(BusinessCashEntry.cost_center),
                selectinload(BusinessCashEntry.funding),
            )
            .where(BusinessCashEntry.business_id == business_id)
            .order_by(BusinessCashEntry.occurred_on.desc(), BusinessCashEntry.created_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.db.scalars(stmt))

    def _list_receipts_for_business(
        self,
        *,
        business_id: UUID,
        start_on: date | None = None,
    ) -> list[Receipt]:
        stmt = (
            select(Receipt)
            .options(selectinload(Receipt.receivable))
            .where(Receipt.business_id == business_id)
            .order_by(Receipt.received_on.asc(), Receipt.created_at.asc())
        )
        if start_on is not None:
            stmt = stmt.where(Receipt.received_on >= start_on)
        return list(self.db.scalars(stmt))

    def _list_fundings_for_business(self, *, business_id: UUID) -> list[BusinessFunding]:
        return list(
            self.db.scalars(
                select(BusinessFunding)
                .options(
                    selectinload(BusinessFunding.disbursement_account),
                    selectinload(BusinessFunding.settlement_account),
                    selectinload(BusinessFunding.payment_category),
                    selectinload(BusinessFunding.cost_center),
                )
                .where(BusinessFunding.business_id == business_id)
                .order_by(BusinessFunding.disbursed_on.desc(), BusinessFunding.created_at.desc())
            )
        )

    def _list_funding_installments_for_business(
        self,
        *,
        business_id: UUID,
        limit: int | None = None,
    ) -> list[BusinessFundingInstallment]:
        stmt = (
            select(BusinessFundingInstallment)
            .options(
                selectinload(BusinessFundingInstallment.funding).selectinload(BusinessFunding.settlement_account),
                selectinload(BusinessFundingInstallment.payment_entry),
            )
            .where(BusinessFundingInstallment.business_id == business_id)
            .order_by(BusinessFundingInstallment.due_on.asc(), BusinessFundingInstallment.installment_number.asc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.db.scalars(stmt))

    def _create_cash_entry_row(
        self,
        *,
        business_id: UUID,
        account_id: UUID,
        category_id: UUID | None,
        cost_center_id: UUID | None,
        funding_id: UUID | None,
        activity_type: BusinessCashActivityType,
        direction: TransactionDirection,
        description: str,
        amount_cents: int,
        occurred_on: date,
        notes: str | None,
    ) -> BusinessCashEntry:
        row = BusinessCashEntry(
            business_id=business_id,
            business_account_id=account_id,
            business_category_id=category_id,
            cost_center_id=cost_center_id,
            funding_id=funding_id,
            activity_type=activity_type,
            direction=direction,
            description=description,
            amount_cents=amount_cents,
            occurred_on=occurred_on,
            notes=notes,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _refresh_overdue_funding_installments(self, *, business_id: UUID) -> None:
        today = date.today()
        rows = list(
            self.db.scalars(
                select(BusinessFundingInstallment).where(
                    BusinessFundingInstallment.business_id == business_id,
                    BusinessFundingInstallment.status.in_(
                        [
                            FundingInstallmentStatus.OPEN,
                            FundingInstallmentStatus.OVERDUE,
                        ]
                    ),
                )
            )
        )
        changed = False
        for row in rows:
            next_status = self._open_installment_status(due_on=row.due_on, reference=today)
            if row.status != next_status:
                row.status = next_status
                self.db.add(row)
                changed = True
        if changed:
            self.db.commit()

    def _get_funding(self, *, business_id: UUID, funding_id: UUID) -> BusinessFunding:
        row = self.db.scalar(
            select(BusinessFunding).where(
                BusinessFunding.id == funding_id,
                BusinessFunding.business_id == business_id,
            )
        )
        if row is None:
            raise ValueError("Financiamento nao encontrado.")
        return row

    def _get_funding_installment(self, *, business_id: UUID, installment_id: UUID) -> BusinessFundingInstallment:
        row = self.db.scalar(
            select(BusinessFundingInstallment)
            .options(
                selectinload(BusinessFundingInstallment.funding).selectinload(BusinessFunding.settlement_account),
            )
            .where(
                BusinessFundingInstallment.id == installment_id,
                BusinessFundingInstallment.business_id == business_id,
            )
        )
        if row is None:
            raise ValueError("Parcela do financiamento nao encontrada.")
        return row

    def _build_daily_growth_points(
        self,
        *,
        business_id: UUID,
        reference: date,
        days: int,
    ) -> list[DailyGrowthPoint]:
        start_on = reference - timedelta(days=days - 1)
        members_by_day = {
            row.reference_date: int(row.total)
            for row in self.db.execute(
                select(
                    Member.joined_on.label("reference_date"),
                    func.count(Member.id).label("total"),
                )
                .where(
                    Member.business_id == business_id,
                    Member.joined_on >= start_on,
                    Member.joined_on <= reference,
                )
                .group_by(Member.joined_on)
            )
        }

        subscriptions_by_day = {
            row.reference_date: int(row.total)
            for row in self.db.execute(
                select(
                    Subscription.started_on.label("reference_date"),
                    func.count(Subscription.id).label("total"),
                )
                .where(
                    Subscription.business_id == business_id,
                    Subscription.started_on >= start_on,
                    Subscription.started_on <= reference,
                )
                .group_by(Subscription.started_on)
            )
        }

        orders_by_day: dict[date, int] = {}
        revenue_by_day: dict[date, int] = {}
        for row in self.db.execute(
            select(
                Receipt.received_on.label("reference_date"),
                func.count(Receipt.id).label("total_orders"),
                func.coalesce(func.sum(Receipt.amount_received_cents), 0).label("total_revenue"),
            )
            .where(
                Receipt.business_id == business_id,
                Receipt.received_on >= start_on,
                Receipt.received_on <= reference,
            )
            .group_by(Receipt.received_on)
        ):
            orders_by_day[row.reference_date] = int(row.total_orders)
            revenue_by_day[row.reference_date] = int(row.total_revenue)

        points: list[DailyGrowthPoint] = []
        for offset in range(days):
            current_day = start_on + timedelta(days=offset)
            points.append(
                DailyGrowthPoint(
                    reference_date=current_day,
                    label=current_day.strftime("%d/%m"),
                    new_members_count=members_by_day.get(current_day, 0),
                    new_subscriptions_count=subscriptions_by_day.get(current_day, 0),
                    paid_orders_count=orders_by_day.get(current_day, 0),
                    revenue_cents=revenue_by_day.get(current_day, 0),
                )
            )
        return points

    @staticmethod
    def _signed_amount(entry: BusinessCashEntry) -> int:
        return entry.amount_cents if entry.direction == TransactionDirection.INCOME else -entry.amount_cents

    @staticmethod
    def _current_cash_cents(*, accounts: list[BusinessAccount], entries: list[BusinessCashEntry]) -> int:
        return sum(item.initial_balance_cents for item in accounts) + sum(
            BusinessControlFinanceService._signed_amount(entry) for entry in entries
        )

    @staticmethod
    def _open_installment_status(*, due_on: date, reference: date) -> FundingInstallmentStatus:
        return FundingInstallmentStatus.OVERDUE if due_on < reference else FundingInstallmentStatus.OPEN

    @staticmethod
    def _installment_balance_cents(row: BusinessFundingInstallment) -> int:
        return max(row.amount_due_cents - row.amount_paid_cents, 0)

    @staticmethod
    def _receipt_note_label(method: ReceiptMethod) -> str:
        labels = {
            ReceiptMethod.PIX: "Recebimento por Pix.",
            ReceiptMethod.BOLETO: "Recebimento por boleto.",
            ReceiptMethod.CARD: "Recebimento por cartao.",
            ReceiptMethod.CASH: "Recebimento em dinheiro.",
            ReceiptMethod.TRANSFER: "Recebimento por transferencia.",
            ReceiptMethod.OTHER: "Recebimento registrado manualmente.",
        }
        return labels[method]

    @staticmethod
    def _assert_active_account(row: BusinessAccount) -> None:
        if not row.is_active:
            raise ValueError("A conta empresarial informada esta inativa.")

    @staticmethod
    def _assert_active_category(row: BusinessCategory) -> None:
        if not row.is_active:
            raise ValueError("A categoria empresarial informada esta inativa.")

    @staticmethod
    def _assert_active_cost_center(row: CostCenter) -> None:
        if not row.is_active:
            raise ValueError("O centro de custo informado esta inativo.")
