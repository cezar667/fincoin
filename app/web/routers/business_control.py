from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.application.dto.business_control_dto import (
    CreateBusinessCashEntryDTO,
    CreateBusinessDTO,
    CreateBusinessFundingDTO,
    CreateMemberDTO,
    CreateSubscriptionDTO,
    PayBusinessFundingInstallmentDTO,
    RecordReceiptDTO,
    UpsertBusinessAccountDTO,
    UpsertBusinessCategoryDTO,
    UpsertCostCenterDTO,
    UpsertMembershipPlanDTO,
)
from app.application.use_cases.business_control import money_to_cents
from app.application.use_cases.business_control_finance import BusinessControlFinanceService
from app.infrastructure.auth.csrf import get_or_create_csrf_token, validate_csrf
from app.infrastructure.db.models.business import Business
from app.infrastructure.db.models.enums import (
    BillingCadence,
    BusinessAccountType,
    BusinessCashActivityType,
    BusinessCategoryKind,
    FundingInstallmentStatus,
    MemberStatus,
    ReceiptMethod,
    ReceivableStatus,
    SubscriptionStatus,
    TransactionDirection,
    WebhookEventStatus,
)
from app.infrastructure.db.session import get_db
from app.web.routers._utils import business_id_from_session, user_id_from_session

router = APIRouter()

BUSINESS_ACCOUNT_TYPE_LABELS = {
    BusinessAccountType.CASH: "Caixa",
    BusinessAccountType.BANK: "Conta bancaria",
    BusinessAccountType.DIGITAL_WALLET: "Carteira digital",
    BusinessAccountType.RECEIVABLE: "Conta de recebimento",
}

BUSINESS_CATEGORY_KIND_LABELS = {
    BusinessCategoryKind.RECURRING_REVENUE: "Receita recorrente",
    BusinessCategoryKind.NON_RECURRING_REVENUE: "Receita nao recorrente",
    BusinessCategoryKind.DEDUCTION: "Deducao",
    BusinessCategoryKind.REFUND: "Estorno",
    BusinessCategoryKind.DISCOUNT: "Desconto",
    BusinessCategoryKind.DIRECT_COST: "Custo direto",
    BusinessCategoryKind.OPERATING_EXPENSE: "Despesa operacional",
    BusinessCategoryKind.ADMIN_EXPENSE: "Despesa administrativa",
    BusinessCategoryKind.FINANCIAL_EXPENSE: "Despesa financeira",
    BusinessCategoryKind.INVESTMENT: "Investimento",
    BusinessCategoryKind.TAX: "Tributo",
}

MEMBER_STATUS_LABELS = {
    MemberStatus.LEAD: "Lead",
    MemberStatus.ACTIVE: "Ativo",
    MemberStatus.SUSPENDED: "Suspenso",
    MemberStatus.BLOCKED: "Bloqueado",
    MemberStatus.CANCELED: "Cancelado",
}

BILLING_CADENCE_LABELS = {
    BillingCadence.MONTHLY: "Mensal",
}

SUBSCRIPTION_STATUS_LABELS = {
    SubscriptionStatus.ACTIVE: "Ativa",
    SubscriptionStatus.SUSPENDED: "Suspensa",
    SubscriptionStatus.BLOCKED: "Bloqueada",
    SubscriptionStatus.CANCELED: "Cancelada",
}

RECEIVABLE_STATUS_LABELS = {
    ReceivableStatus.PLANNED: "Previsto",
    ReceivableStatus.ISSUED: "Emitido",
    ReceivableStatus.PAID: "Pago",
    ReceivableStatus.OVERDUE: "Vencido",
    ReceivableStatus.CANCELED: "Cancelado",
    ReceivableStatus.RENEGOTIATED: "Renegociado",
    ReceivableStatus.REFUNDED: "Estornado",
}

RECEIPT_METHOD_LABELS = {
    ReceiptMethod.PIX: "Pix",
    ReceiptMethod.BOLETO: "Boleto",
    ReceiptMethod.CARD: "Cartao",
    ReceiptMethod.CASH: "Dinheiro",
    ReceiptMethod.TRANSFER: "Transferencia",
    ReceiptMethod.OTHER: "Outro",
}

BUSINESS_CASH_ACTIVITY_TYPE_LABELS = {
    BusinessCashActivityType.OPERATING: "Operacional",
    BusinessCashActivityType.INVESTING: "Investimento",
    BusinessCashActivityType.FINANCING: "Financiamento",
}

TRANSACTION_DIRECTION_LABELS = {
    TransactionDirection.INCOME: "Entrada",
    TransactionDirection.EXPENSE: "Saida",
}

FUNDING_INSTALLMENT_STATUS_LABELS = {
    FundingInstallmentStatus.OPEN: "Aberta",
    FundingInstallmentStatus.PAID: "Paga",
    FundingInstallmentStatus.OVERDUE: "Vencida",
}

WEBHOOK_EVENT_STATUS_LABELS = {
    WebhookEventStatus.RECEIVED: "Recebido",
    WebhookEventStatus.PROCESSED: "Processado",
    WebhookEventStatus.IGNORED: "Ignorado",
    WebhookEventStatus.FAILED: "Falhou",
}


def _set_flash(request: Request, *, kind: str, message: str) -> None:
    request.session["flash_message"] = {"kind": kind, "message": message}


def _business_workspace(
    request: Request,
    db: Session,
) -> tuple[UUID, BusinessControlFinanceService, list[Business], Business | None] | RedirectResponse:
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    service = BusinessControlFinanceService(db)
    businesses = service.list_businesses(owner_user_id=user_id)
    active_business = service.resolve_active_business(
        owner_user_id=user_id,
        requested_business_id=business_id_from_session(request),
    )
    if active_business is None:
        request.session.pop("active_business_id", None)
    else:
        request.session["active_business_id"] = str(active_business.id)
    return user_id, service, businesses, active_business


def _base_context(
    request: Request,
    *,
    businesses: list[Business],
    active_business: Business | None,
    subpage: str,
    flash: dict[str, str] | None,
) -> dict[str, object]:
    return {
        "active_page": "business_control",
        "business_control_subpage": subpage,
        "current_business_name": active_business.name if active_business is not None else None,
        "active_business": active_business,
        "businesses": businesses,
        "flash": flash,
        "today": date.today(),
        "csrf_token": get_or_create_csrf_token(request),
        "business_account_types": [
            {"value": item.value, "label": BUSINESS_ACCOUNT_TYPE_LABELS[item]} for item in BusinessAccountType
        ],
        "business_account_type_labels": {
            item.value: label for item, label in BUSINESS_ACCOUNT_TYPE_LABELS.items()
        },
        "business_category_kinds": [
            {"value": item.value, "label": BUSINESS_CATEGORY_KIND_LABELS[item]} for item in BusinessCategoryKind
        ],
        "business_category_kind_labels": {
            item.value: label for item, label in BUSINESS_CATEGORY_KIND_LABELS.items()
        },
        "member_statuses": [{"value": item.value, "label": MEMBER_STATUS_LABELS[item]} for item in MemberStatus],
        "member_status_labels": {item.value: label for item, label in MEMBER_STATUS_LABELS.items()},
        "billing_cadences": [{"value": item.value, "label": BILLING_CADENCE_LABELS[item]} for item in BillingCadence],
        "billing_cadence_labels": {item.value: label for item, label in BILLING_CADENCE_LABELS.items()},
        "subscription_status_labels": {
            item.value: label for item, label in SUBSCRIPTION_STATUS_LABELS.items()
        },
        "receivable_status_labels": {
            item.value: label for item, label in RECEIVABLE_STATUS_LABELS.items()
        },
        "receipt_methods": [{"value": item.value, "label": RECEIPT_METHOD_LABELS[item]} for item in ReceiptMethod],
        "receipt_method_labels": {item.value: label for item, label in RECEIPT_METHOD_LABELS.items()},
        "business_cash_activity_types": [
            {"value": item.value, "label": BUSINESS_CASH_ACTIVITY_TYPE_LABELS[item]}
            for item in BusinessCashActivityType
        ],
        "business_cash_activity_type_labels": {
            item.value: label for item, label in BUSINESS_CASH_ACTIVITY_TYPE_LABELS.items()
        },
        "transaction_directions": [
            {"value": item.value, "label": TRANSACTION_DIRECTION_LABELS[item]} for item in TransactionDirection
        ],
        "transaction_direction_labels": {
            item.value: label for item, label in TRANSACTION_DIRECTION_LABELS.items()
        },
        "funding_installment_status_labels": {
            item.value: label for item, label in FUNDING_INSTALLMENT_STATUS_LABELS.items()
        },
        "webhook_event_status_labels": {
            item.value: label for item, label in WEBHOOK_EVENT_STATUS_LABELS.items()
        },
        "primary_action_href": "/app/business-control/members",
        "primary_action_label": "+ Associado",
    }


def _optional_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    return UUID(raw)


@router.get("/app/business-control")
def business_control_dashboard(request: Request, db: Session = Depends(get_db)):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, businesses, active_business = workspace
    dashboard = None
    if active_business is not None:
        dashboard = service.build_dashboard(owner_user_id=user_id, business_id=active_business.id)
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="business_control/index.html",
        context={
            **_base_context(
                request,
                businesses=businesses,
                active_business=active_business,
                subpage="dashboard",
                flash=request.session.pop("flash_message", None),
            ),
            "dashboard": dashboard,
        },
    )


@router.get("/app/business-control/businesses")
def businesses_page(request: Request, db: Session = Depends(get_db)):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    _, _, businesses, active_business = workspace
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="business_control/businesses.html",
        context=_base_context(
            request,
            businesses=businesses,
            active_business=active_business,
            subpage="businesses",
            flash=request.session.pop("flash_message", None),
        ),
    )


@router.get("/app/business-control/accounts")
def business_accounts_page(request: Request, db: Session = Depends(get_db)):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, businesses, active_business = workspace
    accounts = []
    if active_business is not None:
        accounts = service.list_accounts(owner_user_id=user_id, business_id=active_business.id)
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="business_control/accounts.html",
        context={
            **_base_context(
                request,
                businesses=businesses,
                active_business=active_business,
                subpage="accounts",
                flash=request.session.pop("flash_message", None),
            ),
            "accounts": accounts,
        },
    )


@router.get("/app/business-control/categories")
def business_categories_page(request: Request, db: Session = Depends(get_db)):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, businesses, active_business = workspace
    categories = []
    if active_business is not None:
        categories = service.list_categories(owner_user_id=user_id, business_id=active_business.id)
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="business_control/categories.html",
        context={
            **_base_context(
                request,
                businesses=businesses,
                active_business=active_business,
                subpage="categories",
                flash=request.session.pop("flash_message", None),
            ),
            "categories": categories,
        },
    )


@router.get("/app/business-control/cost-centers")
def cost_centers_page(request: Request, db: Session = Depends(get_db)):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, businesses, active_business = workspace
    cost_centers = []
    if active_business is not None:
        cost_centers = service.list_cost_centers(owner_user_id=user_id, business_id=active_business.id)
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="business_control/cost_centers.html",
        context={
            **_base_context(
                request,
                businesses=businesses,
                active_business=active_business,
                subpage="cost_centers",
                flash=request.session.pop("flash_message", None),
            ),
            "cost_centers": cost_centers,
        },
    )


@router.get("/app/business-control/members")
def members_page(request: Request, db: Session = Depends(get_db)):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, businesses, active_business = workspace
    members = []
    if active_business is not None:
        members = service.list_members(owner_user_id=user_id, business_id=active_business.id)
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="business_control/members.html",
        context={
            **_base_context(
                request,
                businesses=businesses,
                active_business=active_business,
                subpage="members",
                flash=request.session.pop("flash_message", None),
            ),
            "members": members,
        },
    )


@router.get("/app/business-control/membership-plans")
def membership_plans_page(request: Request, db: Session = Depends(get_db)):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, businesses, active_business = workspace
    plans = []
    if active_business is not None:
        plans = service.list_membership_plans(owner_user_id=user_id, business_id=active_business.id)
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="business_control/membership_plans.html",
        context={
            **_base_context(
                request,
                businesses=businesses,
                active_business=active_business,
                subpage="membership_plans",
                flash=request.session.pop("flash_message", None),
            ),
            "plans": plans,
        },
    )


@router.get("/app/business-control/subscriptions")
def subscriptions_page(request: Request, db: Session = Depends(get_db)):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, businesses, active_business = workspace
    subscriptions = []
    members = []
    plans = []
    if active_business is not None:
        subscriptions = service.list_subscriptions(owner_user_id=user_id, business_id=active_business.id)
        members = service.list_members(owner_user_id=user_id, business_id=active_business.id)
        plans = service.list_membership_plans(owner_user_id=user_id, business_id=active_business.id)
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="business_control/subscriptions.html",
        context={
            **_base_context(
                request,
                businesses=businesses,
                active_business=active_business,
                subpage="subscriptions",
                flash=request.session.pop("flash_message", None),
            ),
            "subscriptions": subscriptions,
            "members": members,
            "plans": plans,
        },
    )


@router.get("/app/business-control/receivables")
def receivables_page(request: Request, db: Session = Depends(get_db)):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, businesses, active_business = workspace
    receivables = []
    if active_business is not None:
        receivables = service.list_receivables(owner_user_id=user_id, business_id=active_business.id)
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="business_control/receivables.html",
        context={
            **_base_context(
                request,
                businesses=businesses,
                active_business=active_business,
                subpage="receivables",
                flash=request.session.pop("flash_message", None),
            ),
            "receivables": receivables,
            "open_receivable_count": sum(
                1
                for item in receivables
                if item.status.value in {
                    ReceivableStatus.PLANNED.value,
                    ReceivableStatus.ISSUED.value,
                    ReceivableStatus.OVERDUE.value,
                }
            ),
            "overdue_receivable_count": sum(
                1 for item in receivables if item.status.value == ReceivableStatus.OVERDUE.value
            ),
            "paid_receivable_count": sum(
                1 for item in receivables if item.status.value == ReceivableStatus.PAID.value
            ),
            "receivable_balance_map": {
                item.id: service._receivable_balance_cents(item) for item in receivables
            }
            if active_business is not None
            else {},
        },
    )


@router.get("/app/business-control/cash-flow")
def cash_flow_page(request: Request, db: Session = Depends(get_db)):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, businesses, active_business = workspace
    dashboard = None
    cash_entries = []
    accounts = []
    categories = []
    cost_centers = []
    fundings = []
    if active_business is not None:
        dashboard = service.build_dashboard(owner_user_id=user_id, business_id=active_business.id)
        cash_entries = service.list_cash_entries(owner_user_id=user_id, business_id=active_business.id, limit=60)
        accounts = service.list_accounts(owner_user_id=user_id, business_id=active_business.id)
        categories = service.list_categories(owner_user_id=user_id, business_id=active_business.id)
        cost_centers = service.list_cost_centers(owner_user_id=user_id, business_id=active_business.id)
        fundings = service.list_fundings(owner_user_id=user_id, business_id=active_business.id)
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="business_control/cash_flow.html",
        context={
            **_base_context(
                request,
                businesses=businesses,
                active_business=active_business,
                subpage="cash_flow",
                flash=request.session.pop("flash_message", None),
            ),
            "dashboard": dashboard,
            "cash_entries": cash_entries,
            "accounts": accounts,
            "categories": categories,
            "cost_centers": cost_centers,
            "fundings": fundings,
        },
    )


@router.get("/app/business-control/fundings")
def fundings_page(request: Request, db: Session = Depends(get_db)):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, businesses, active_business = workspace
    dashboard = None
    funding_snapshots = []
    installments = []
    accounts = []
    categories = []
    cost_centers = []
    if active_business is not None:
        dashboard = service.build_dashboard(owner_user_id=user_id, business_id=active_business.id)
        funding_snapshots = service.list_funding_snapshots(owner_user_id=user_id, business_id=active_business.id)
        installments = service.list_funding_installments(
            owner_user_id=user_id,
            business_id=active_business.id,
            limit=80,
        )
        accounts = service.list_accounts(owner_user_id=user_id, business_id=active_business.id)
        categories = service.list_categories(owner_user_id=user_id, business_id=active_business.id)
        cost_centers = service.list_cost_centers(owner_user_id=user_id, business_id=active_business.id)
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="business_control/fundings.html",
        context={
            **_base_context(
                request,
                businesses=businesses,
                active_business=active_business,
                subpage="fundings",
                flash=request.session.pop("flash_message", None),
            ),
            "dashboard": dashboard,
            "funding_snapshots": funding_snapshots,
            "installments": installments,
            "accounts": accounts,
            "categories": categories,
            "cost_centers": cost_centers,
            "open_installment_count": sum(
                1 for item in installments if item.status.value == FundingInstallmentStatus.OPEN.value
            ),
            "overdue_installment_count": sum(
                1 for item in installments if item.status.value == FundingInstallmentStatus.OVERDUE.value
            ),
            "paid_installment_count": sum(
                1 for item in installments if item.status.value == FundingInstallmentStatus.PAID.value
            ),
            "installment_balance_map": {
                item.id: service._installment_balance_cents(item) for item in installments
            }
            if active_business is not None
            else {},
        },
    )


@router.get("/app/business-control/integrations")
def integrations_page(request: Request, db: Session = Depends(get_db)):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, businesses, active_business = workspace
    integration = None
    integration_events = []
    plans = []
    integration_webhook_url = None
    if active_business is not None:
        integration = service.get_checkout_integration(
            owner_user_id=user_id,
            business_id=active_business.id,
        )
        integration_events = service.list_checkout_events(
            owner_user_id=user_id,
            business_id=active_business.id,
        )
        plans = service.list_membership_plans(
            owner_user_id=user_id,
            business_id=active_business.id,
        )
        if integration is not None:
            integration_webhook_url = service.build_checkout_webhook_url(integration)
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="business_control/integrations.html",
        context={
            **_base_context(
                request,
                businesses=businesses,
                active_business=active_business,
                subpage="integrations",
                flash=request.session.pop("flash_message", None),
            ),
            "integration": integration,
            "integration_events": integration_events,
            "integration_webhook_url": integration_webhook_url,
            "plans": plans,
        },
    )


@router.post("/app/business-control/businesses")
def create_business_form(
    request: Request,
    name: str = Form(...),
    slug: str = Form(...),
    legal_name: str | None = Form(default=None),
    description: str | None = Form(default=None),
    seed_template: str | None = Form(default=None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, _ = workspace
    validate_csrf(request, csrf_token)
    try:
        payload = CreateBusinessDTO(
            name=name,
            slug=slug,
            legal_name=legal_name,
            description=description,
            seed_template=seed_template,
        )
        row = service.create_business(
            actor_user_id=user_id,
            payload=payload,
            request_id=request.state.request_id,
        )
        request.session["active_business_id"] = str(row.id)
        _set_flash(request, kind="ok", message="Business criado com sucesso.")
    except (ValidationError, ValueError) as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/businesses", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/businesses/{business_id}/switch")
def switch_business_form(
    business_id: UUID,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, _ = workspace
    validate_csrf(request, csrf_token)
    try:
        row = service.switch_business(
            actor_user_id=user_id,
            business_id=business_id,
            request_id=request.state.request_id,
        )
        request.session["active_business_id"] = str(row.id)
        _set_flash(request, kind="ok", message=f"Business ativo: {row.name}.")
    except ValueError as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/businesses", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/businesses/{business_id}/toggle")
def toggle_business_form(
    business_id: UUID,
    request: Request,
    is_active: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, _ = workspace
    validate_csrf(request, csrf_token)
    try:
        row = service.set_business_active(
            actor_user_id=user_id,
            business_id=business_id,
            is_active=is_active.strip().lower() == "true",
            request_id=request.state.request_id,
        )
        next_active = service.resolve_active_business(
            owner_user_id=user_id,
            requested_business_id=business_id_from_session(request),
        )
        if next_active is None:
            request.session.pop("active_business_id", None)
        else:
            request.session["active_business_id"] = str(next_active.id)
        _set_flash(request, kind="ok", message=f"Business {row.name} atualizado.")
    except ValueError as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/businesses", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/accounts")
def create_business_account_form(
    request: Request,
    name: str = Form(...),
    account_type: str = Form(...),
    institution_name: str | None = Form(default=None),
    initial_balance: str = Form("0"),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        _set_flash(request, kind="error", message="Crie um business antes de cadastrar contas.")
        return RedirectResponse("/app/business-control/accounts", status_code=status.HTTP_303_SEE_OTHER)
    try:
        payload = UpsertBusinessAccountDTO(
            name=name,
            type=BusinessAccountType(account_type),
            institution_name=institution_name,
            initial_balance_cents=money_to_cents(initial_balance),
        )
        service.create_account(
            actor_user_id=user_id,
            business_id=active_business.id,
            payload=payload,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Conta empresarial criada.")
    except (ValidationError, ValueError) as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/accounts", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/accounts/{account_id}/update")
def update_business_account_form(
    account_id: UUID,
    request: Request,
    name: str = Form(...),
    account_type: str = Form(...),
    institution_name: str | None = Form(default=None),
    initial_balance: str = Form("0"),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/accounts", status_code=status.HTTP_303_SEE_OTHER)
    try:
        payload = UpsertBusinessAccountDTO(
            name=name,
            type=BusinessAccountType(account_type),
            institution_name=institution_name,
            initial_balance_cents=money_to_cents(initial_balance),
        )
        service.update_account(
            actor_user_id=user_id,
            business_id=active_business.id,
            account_id=account_id,
            payload=payload,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Conta empresarial atualizada.")
    except (ValidationError, ValueError) as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/accounts", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/accounts/{account_id}/toggle")
def toggle_business_account_form(
    account_id: UUID,
    request: Request,
    is_active: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/accounts", status_code=status.HTTP_303_SEE_OTHER)
    try:
        service.set_account_active(
            actor_user_id=user_id,
            business_id=active_business.id,
            account_id=account_id,
            is_active=is_active.strip().lower() == "true",
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Conta empresarial atualizada.")
    except ValueError as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/accounts", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/categories")
def create_business_category_form(
    request: Request,
    code: str | None = Form(default=None),
    name: str = Form(...),
    kind: str = Form(...),
    description: str | None = Form(default=None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        _set_flash(request, kind="error", message="Crie um business antes de cadastrar categorias.")
        return RedirectResponse("/app/business-control/categories", status_code=status.HTTP_303_SEE_OTHER)
    try:
        payload = UpsertBusinessCategoryDTO(
            code=code,
            name=name,
            kind=BusinessCategoryKind(kind),
            description=description,
        )
        service.create_category(
            actor_user_id=user_id,
            business_id=active_business.id,
            payload=payload,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Categoria empresarial criada.")
    except (ValidationError, ValueError) as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/categories", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/categories/{category_id}/update")
def update_business_category_form(
    category_id: UUID,
    request: Request,
    code: str | None = Form(default=None),
    name: str = Form(...),
    kind: str = Form(...),
    description: str | None = Form(default=None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/categories", status_code=status.HTTP_303_SEE_OTHER)
    try:
        payload = UpsertBusinessCategoryDTO(
            code=code,
            name=name,
            kind=BusinessCategoryKind(kind),
            description=description,
        )
        service.update_category(
            actor_user_id=user_id,
            business_id=active_business.id,
            category_id=category_id,
            payload=payload,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Categoria empresarial atualizada.")
    except (ValidationError, ValueError) as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/categories", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/categories/{category_id}/toggle")
def toggle_business_category_form(
    category_id: UUID,
    request: Request,
    is_active: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/categories", status_code=status.HTTP_303_SEE_OTHER)
    try:
        service.set_category_active(
            actor_user_id=user_id,
            business_id=active_business.id,
            category_id=category_id,
            is_active=is_active.strip().lower() == "true",
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Categoria empresarial atualizada.")
    except ValueError as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/categories", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/cost-centers")
def create_cost_center_form(
    request: Request,
    code: str | None = Form(default=None),
    name: str = Form(...),
    description: str | None = Form(default=None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        _set_flash(request, kind="error", message="Crie um business antes de cadastrar centros de custo.")
        return RedirectResponse("/app/business-control/cost-centers", status_code=status.HTTP_303_SEE_OTHER)
    try:
        payload = UpsertCostCenterDTO(code=code, name=name, description=description)
        service.create_cost_center(
            actor_user_id=user_id,
            business_id=active_business.id,
            payload=payload,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Centro de custo criado.")
    except (ValidationError, ValueError) as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/cost-centers", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/cost-centers/{cost_center_id}/update")
def update_cost_center_form(
    cost_center_id: UUID,
    request: Request,
    code: str | None = Form(default=None),
    name: str = Form(...),
    description: str | None = Form(default=None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/cost-centers", status_code=status.HTTP_303_SEE_OTHER)
    try:
        payload = UpsertCostCenterDTO(code=code, name=name, description=description)
        service.update_cost_center(
            actor_user_id=user_id,
            business_id=active_business.id,
            cost_center_id=cost_center_id,
            payload=payload,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Centro de custo atualizado.")
    except (ValidationError, ValueError) as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/cost-centers", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/cost-centers/{cost_center_id}/toggle")
def toggle_cost_center_form(
    cost_center_id: UUID,
    request: Request,
    is_active: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/cost-centers", status_code=status.HTTP_303_SEE_OTHER)
    try:
        service.set_cost_center_active(
            actor_user_id=user_id,
            business_id=active_business.id,
            cost_center_id=cost_center_id,
            is_active=is_active.strip().lower() == "true",
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Centro de custo atualizado.")
    except ValueError as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/cost-centers", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/members")
def create_member_form(
    request: Request,
    full_name: str = Form(...),
    email: str | None = Form(default=None),
    phone: str | None = Form(default=None),
    document_number: str | None = Form(default=None),
    status_value: str = Form(..., alias="status"),
    joined_on: str = Form(...),
    notes: str | None = Form(default=None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/members", status_code=status.HTTP_303_SEE_OTHER)
    try:
        payload = CreateMemberDTO(
            full_name=full_name,
            email=email,
            phone=phone,
            document_number=document_number,
            status=MemberStatus(status_value),
            joined_on=joined_on,
            notes=notes,
        )
        service.create_member(
            actor_user_id=user_id,
            business_id=active_business.id,
            payload=payload,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Associado cadastrado.")
    except (ValidationError, ValueError) as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/members", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/members/{member_id}/status")
def update_member_status_form(
    member_id: UUID,
    request: Request,
    status_value: str = Form(..., alias="status"),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/members", status_code=status.HTTP_303_SEE_OTHER)
    try:
        service.set_member_status(
            actor_user_id=user_id,
            business_id=active_business.id,
            member_id=member_id,
            status=MemberStatus(status_value),
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Status do associado atualizado.")
    except ValueError as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/members", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/membership-plans")
def create_membership_plan_form(
    request: Request,
    name: str = Form(...),
    description: str | None = Form(default=None),
    external_product_id: str | None = Form(default=None),
    external_reference_id: str | None = Form(default=None),
    cadence: str = Form(...),
    recurring_amount: str = Form(...),
    activation_fee: str = Form("0"),
    billing_day: int = Form(...),
    grace_days: int = Form(0),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/membership-plans", status_code=status.HTTP_303_SEE_OTHER)
    try:
        payload = UpsertMembershipPlanDTO(
            name=name,
            description=description,
            external_product_id=external_product_id,
            external_reference_id=external_reference_id,
            cadence=BillingCadence(cadence),
            recurring_amount_cents=money_to_cents(recurring_amount),
            activation_fee_cents=money_to_cents(activation_fee),
            billing_day=billing_day,
            grace_days=grace_days,
        )
        service.create_membership_plan(
            actor_user_id=user_id,
            business_id=active_business.id,
            payload=payload,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Plano cadastrado.")
    except (ValidationError, ValueError) as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/membership-plans", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/membership-plans/{plan_id}/update")
def update_membership_plan_form(
    plan_id: UUID,
    request: Request,
    name: str = Form(...),
    description: str | None = Form(default=None),
    external_product_id: str | None = Form(default=None),
    external_reference_id: str | None = Form(default=None),
    cadence: str = Form(...),
    recurring_amount: str = Form(...),
    activation_fee: str = Form("0"),
    billing_day: int = Form(...),
    grace_days: int = Form(0),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/membership-plans", status_code=status.HTTP_303_SEE_OTHER)
    try:
        payload = UpsertMembershipPlanDTO(
            name=name,
            description=description,
            external_product_id=external_product_id,
            external_reference_id=external_reference_id,
            cadence=BillingCadence(cadence),
            recurring_amount_cents=money_to_cents(recurring_amount),
            activation_fee_cents=money_to_cents(activation_fee),
            billing_day=billing_day,
            grace_days=grace_days,
        )
        service.update_membership_plan(
            actor_user_id=user_id,
            business_id=active_business.id,
            plan_id=plan_id,
            payload=payload,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Plano atualizado.")
    except (ValidationError, ValueError) as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/membership-plans", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/membership-plans/{plan_id}/toggle")
def toggle_membership_plan_form(
    plan_id: UUID,
    request: Request,
    is_active: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/membership-plans", status_code=status.HTTP_303_SEE_OTHER)
    try:
        service.set_membership_plan_active(
            actor_user_id=user_id,
            business_id=active_business.id,
            plan_id=plan_id,
            is_active=is_active.strip().lower() == "true",
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Plano atualizado.")
    except ValueError as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/membership-plans", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/subscriptions")
def create_subscription_form(
    request: Request,
    member_id: UUID = Form(...),
    membership_plan_id: UUID = Form(...),
    started_on: str = Form(...),
    first_due_on: str = Form(...),
    price_override: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/subscriptions", status_code=status.HTTP_303_SEE_OTHER)
    try:
        override_cents = None
        if price_override is not None and price_override.strip():
            override_cents = money_to_cents(price_override)
        payload = CreateSubscriptionDTO(
            member_id=member_id,
            membership_plan_id=membership_plan_id,
            started_on=started_on,
            first_due_on=first_due_on,
            price_override_cents=override_cents,
            notes=notes,
        )
        service.create_subscription(
            actor_user_id=user_id,
            business_id=active_business.id,
            payload=payload,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Assinatura criada com cobranca inicial.")
    except (ValidationError, ValueError) as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/subscriptions", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/subscriptions/{subscription_id}/status")
def update_subscription_status_form(
    subscription_id: UUID,
    request: Request,
    status_value: str = Form(..., alias="status"),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/subscriptions", status_code=status.HTTP_303_SEE_OTHER)
    try:
        service.set_subscription_status(
            actor_user_id=user_id,
            business_id=active_business.id,
            subscription_id=subscription_id,
            status=SubscriptionStatus(status_value),
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Assinatura atualizada.")
    except ValueError as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/subscriptions", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/subscriptions/{subscription_id}/generate")
def generate_subscription_receivable_form(
    subscription_id: UUID,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/subscriptions", status_code=status.HTTP_303_SEE_OTHER)
    try:
        service.generate_next_receivable(
            actor_user_id=user_id,
            business_id=active_business.id,
            subscription_id=subscription_id,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Nova cobranca gerada.")
    except ValueError as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/subscriptions", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/receivables/{receivable_id}/receive")
def record_receipt_form(
    receivable_id: UUID,
    request: Request,
    received_on: str = Form(...),
    amount_received: str = Form(...),
    method: str = Form(...),
    note: str | None = Form(default=None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/receivables", status_code=status.HTTP_303_SEE_OTHER)
    try:
        payload = RecordReceiptDTO(
            received_on=received_on,
            amount_received_cents=money_to_cents(amount_received),
            method=ReceiptMethod(method),
            note=note,
        )
        service.record_receipt(
            actor_user_id=user_id,
            business_id=active_business.id,
            receivable_id=receivable_id,
            payload=payload,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Recebimento registrado.")
    except (ValidationError, ValueError) as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/receivables", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/cash-flow")
def create_cash_entry_form(
    request: Request,
    business_account_id: UUID = Form(...),
    activity_type: str = Form(...),
    direction: str = Form(...),
    description: str = Form(...),
    amount: str = Form(...),
    occurred_on: str = Form(...),
    business_category_id: str | None = Form(default=None),
    cost_center_id: str | None = Form(default=None),
    funding_id: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/cash-flow", status_code=status.HTTP_303_SEE_OTHER)
    try:
        payload = CreateBusinessCashEntryDTO(
            business_account_id=business_account_id,
            business_category_id=_optional_uuid(business_category_id),
            cost_center_id=_optional_uuid(cost_center_id),
            funding_id=_optional_uuid(funding_id),
            activity_type=BusinessCashActivityType(activity_type),
            direction=TransactionDirection(direction),
            description=description,
            amount_cents=money_to_cents(amount),
            occurred_on=occurred_on,
            notes=notes,
        )
        service.create_cash_entry(
            actor_user_id=user_id,
            business_id=active_business.id,
            payload=payload,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Lancamento de caixa registrado.")
    except (ValidationError, ValueError) as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/cash-flow", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/fundings")
def create_funding_form(
    request: Request,
    name: str = Form(...),
    lender_name: str | None = Form(default=None),
    disbursement_account_id: UUID = Form(...),
    settlement_account_id: UUID = Form(...),
    payment_category_id: str | None = Form(default=None),
    cost_center_id: str | None = Form(default=None),
    principal: str = Form(...),
    installment_amount: str = Form(...),
    installment_count: int = Form(...),
    annual_interest_rate: str | None = Form(default=None),
    disbursed_on: str = Form(...),
    first_due_on: str = Form(...),
    notes: str | None = Form(default=None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/fundings", status_code=status.HTTP_303_SEE_OTHER)
    try:
        annual_interest_bps = None
        if annual_interest_rate is not None and annual_interest_rate.strip():
            annual_interest_bps = money_to_cents(annual_interest_rate)
        payload = CreateBusinessFundingDTO(
            name=name,
            lender_name=lender_name,
            disbursement_account_id=disbursement_account_id,
            settlement_account_id=settlement_account_id,
            payment_category_id=_optional_uuid(payment_category_id),
            cost_center_id=_optional_uuid(cost_center_id),
            principal_cents=money_to_cents(principal),
            installment_amount_cents=money_to_cents(installment_amount),
            installment_count=installment_count,
            annual_interest_bps=annual_interest_bps,
            disbursed_on=disbursed_on,
            first_due_on=first_due_on,
            notes=notes,
        )
        service.create_funding(
            actor_user_id=user_id,
            business_id=active_business.id,
            payload=payload,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Financiamento cadastrado com parcelas geradas.")
    except (ValidationError, ValueError) as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/fundings", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/fundings/installments/{installment_id}/pay")
def pay_funding_installment_form(
    installment_id: UUID,
    request: Request,
    paid_on: str = Form(...),
    amount_paid: str = Form(...),
    notes: str | None = Form(default=None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/fundings", status_code=status.HTTP_303_SEE_OTHER)
    try:
        payload = PayBusinessFundingInstallmentDTO(
            paid_on=paid_on,
            amount_paid_cents=money_to_cents(amount_paid),
            notes=notes,
        )
        service.pay_funding_installment(
            actor_user_id=user_id,
            business_id=active_business.id,
            installment_id=installment_id,
            payload=payload,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message="Parcela quitada e lancada no caixa.")
    except (ValidationError, ValueError) as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/fundings", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/integrations/themembers/provision")
def provision_themembers_integration_form(
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/integrations", status_code=status.HTTP_303_SEE_OTHER)
    try:
        result = service.create_checkout_integration(
            actor_user_id=user_id,
            business_id=active_business.id,
            request_id=request.state.request_id,
        )
        _set_flash(
            request,
            kind="ok",
            message=(
                f"Integracao provisionada. URL: {result.webhook_url} | "
                f"Token de seguranca: {result.webhook_secret}"
            ),
        )
    except ValueError as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/integrations", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/integrations/themembers/rotate-secret")
def rotate_themembers_secret_form(
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/integrations", status_code=status.HTTP_303_SEE_OTHER)
    try:
        result = service.rotate_checkout_secret(
            actor_user_id=user_id,
            business_id=active_business.id,
            request_id=request.state.request_id,
        )
        _set_flash(
            request,
            kind="ok",
            message=f"Token rotacionado. Novo token de seguranca: {result.webhook_secret}",
        )
    except ValueError as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/integrations", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/business-control/integrations/themembers/events/{event_id}/reprocess")
def reprocess_themembers_event_form(
    event_id: UUID,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    workspace = _business_workspace(request, db)
    if isinstance(workspace, RedirectResponse):
        return workspace
    user_id, service, _, active_business = workspace
    validate_csrf(request, csrf_token)
    if active_business is None:
        return RedirectResponse("/app/business-control/integrations", status_code=status.HTTP_303_SEE_OTHER)
    try:
        result = service.reprocess_checkout_event(
            actor_user_id=user_id,
            business_id=active_business.id,
            event_id=event_id,
            request_id=request.state.request_id,
        )
        _set_flash(request, kind="ok", message=f"Evento reprocessado com status {result.status}.")
    except ValueError as exc:
        db.rollback()
        _set_flash(request, kind="error", message=str(exc))
    return RedirectResponse("/app/business-control/integrations", status_code=status.HTTP_303_SEE_OTHER)
