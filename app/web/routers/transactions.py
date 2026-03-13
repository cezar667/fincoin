from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.dto.transaction_dto import CreateTransactionDTO, TransactionReadDTO, UpdateTransactionDTO
from app.application.use_cases.create_transaction import CreateTransactionUseCase
from app.application.use_cases.update_transaction import UpdateTransactionUseCase
from app.domain.value_objects.month import Month
from app.infrastructure.auth.csrf import get_or_create_csrf_token, validate_csrf
from app.infrastructure.auth.session import get_current_user_id
from app.infrastructure.db.models.account import Account
from app.infrastructure.db.models.category import Category
from app.infrastructure.db.models.credit_card import CreditCard
from app.infrastructure.db.models.enums import AccountType, CategoryKind, RecurringCadence, TransactionDirection
from app.infrastructure.db.models.financial_plan import FinancialPlan
from app.infrastructure.db.models.installment import Installment
from app.infrastructure.db.models.plan_installment import PlanInstallment
from app.infrastructure.db.models.plan_recurring_rule import PlanRecurringRule
from app.infrastructure.db.models.plan_transaction import PlanTransaction
from app.infrastructure.db.models.recurring_rule import RecurringRule
from app.infrastructure.db.models.transaction import Transaction
from app.infrastructure.db.session import get_db
from app.infrastructure.repositories.transaction_repo import SQLAlchemyTransactionRepository
from app.web.routers._utils import parse_year_month, plan_id_from_session, user_id_from_session

router = APIRouter()

ACCOUNT_TYPE_LABELS = {
    AccountType.CASH: "Dinheiro em especie",
    AccountType.BANK: "Conta bancaria",
    AccountType.WALLET: "Carteira digital",
}
CATEGORY_KIND_LABELS = {
    CategoryKind.INCOME: "Receita",
    CategoryKind.EXPENSE: "Despesa",
}
TRANSACTION_DIRECTION_LABELS = {
    TransactionDirection.INCOME: "Entrada",
    TransactionDirection.EXPENSE: "Saida",
}


def _set_flash(request: Request, *, kind: str, message: str) -> None:
    request.session["flash_message"] = {"kind": kind, "message": message}


def _month_from_input(value: str) -> date:
    try:
        year, month = value.split("-", maxsplit=1)
        return date(int(year), int(month), 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("Mes de competencia invalido. Use YYYY-MM.") from exc


def _month_from_optional_input(value: str | None) -> date | None:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return _month_from_input(trimmed)


def _money_to_cents(value: str) -> int:
    try:
        parsed = Decimal(value.replace(",", ".").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("Valor monetario invalido.") from exc
    if parsed <= 0:
        raise ValueError("Valor deve ser maior que zero.")
    return int((parsed * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _signed_money_to_cents(value: str) -> int:
    try:
        parsed = Decimal(value.replace(",", ".").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("Valor monetario invalido.") from exc
    return int((parsed * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _is_checked(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "on", "yes", "sim"}


def _resolve_user_and_plan(request: Request, db: Session) -> tuple[UUID, FinancialPlan] | RedirectResponse:
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    plan_id = plan_id_from_session(request)
    if plan_id is None:
        return RedirectResponse("/app/plans", status_code=status.HTTP_303_SEE_OTHER)
    plan = db.scalar(
        select(FinancialPlan).where(
            FinancialPlan.id == plan_id,
            FinancialPlan.user_id == user_id,
        )
    )
    if plan is None:
        request.session.pop("active_plan_id", None)
        return RedirectResponse("/app/plans", status_code=status.HTTP_303_SEE_OTHER)
    return user_id, plan


def _base_context(
    request: Request,
    *,
    plan: FinancialPlan,
    subpage: str,
    flash: dict[str, str] | None,
) -> dict[str, object]:
    return {
        "active_page": "transactions",
        "transactions_subpage": subpage,
        "current_plan_name": plan.name,
        "csrf_token": get_or_create_csrf_token(request),
        "flash": flash,
        "today": date.today(),
        "account_types": [{"value": item.value, "label": ACCOUNT_TYPE_LABELS[item]} for item in AccountType],
        "account_type_labels": {item.value: label for item, label in ACCOUNT_TYPE_LABELS.items()},
        "category_kinds": [{"value": item.value, "label": CATEGORY_KIND_LABELS[item]} for item in CategoryKind],
        "category_kind_labels": {item.value: label for item, label in CATEGORY_KIND_LABELS.items()},
        "transaction_directions": [
            {"value": item.value, "label": TRANSACTION_DIRECTION_LABELS[item]}
            for item in TransactionDirection
        ],
        "transaction_direction_labels": {
            item.value: label for item, label in TRANSACTION_DIRECTION_LABELS.items()
        },
        "direction_income_value": TransactionDirection.INCOME.value,
    }


@router.get("/app/transactions")
def transactions_page(
    request: Request,
    month: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx

    selected_month = parse_year_month(month, default=date.today())
    selected_direction = (direction or "").strip().upper()
    allowed = {item.value for item in TransactionDirection}
    if selected_direction and selected_direction not in allowed:
        selected_direction = ""

    repo = SQLAlchemyTransactionRepository(db)
    items = repo.list_by_month(user_id=user_id, month=selected_month, plan_id=plan.id)
    if selected_direction:
        items = [item for item in items if item.direction.value == selected_direction]

    accounts = list(db.scalars(select(Account).where(Account.user_id == user_id).order_by(Account.name.asc())))
    categories = list(
        db.scalars(
            select(Category).where(Category.user_id == user_id).order_by(Category.kind.asc(), Category.name.asc())
        )
    )
    income_total = sum(item.amount_cents for item in items if item.direction == TransactionDirection.INCOME)
    expense_total = sum(item.amount_cents for item in items if item.direction == TransactionDirection.EXPENSE)

    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="transactions/index.html",
        context={
            **_base_context(
                request,
                plan=plan,
                subpage="transactions",
                flash=request.session.pop("flash_message", None),
            ),
            "selected_month": selected_month,
            "selected_direction": selected_direction,
            "transactions": items,
            "accounts": accounts,
            "categories": categories,
            "account_name_map": {item.id: item.name for item in accounts},
            "category_name_map": {item.id: item.name for item in categories},
            "income_total": income_total,
            "expense_total": expense_total,
            "net_total": income_total - expense_total,
            "transaction_count": len(items),
        },
    )


@router.get("/app/transactions/accounts")
def accounts_page(request: Request, db: Session = Depends(get_db)):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx
    accounts = list(db.scalars(select(Account).where(Account.user_id == user_id).order_by(Account.name.asc())))
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="transactions/accounts.html",
        context={
            **_base_context(
                request,
                plan=plan,
                subpage="accounts",
                flash=request.session.pop("flash_message", None),
            ),
            "accounts": accounts,
        },
    )


@router.get("/app/transactions/categories")
def categories_page(request: Request, db: Session = Depends(get_db)):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx
    categories = list(
        db.scalars(
            select(Category).where(Category.user_id == user_id).order_by(Category.kind.asc(), Category.name.asc())
        )
    )
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="transactions/categories.html",
        context={
            **_base_context(
                request,
                plan=plan,
                subpage="categories",
                flash=request.session.pop("flash_message", None),
            ),
            "categories": categories,
        },
    )


@router.get("/app/transactions/cards")
def cards_page(request: Request, db: Session = Depends(get_db)):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx
    cards = list(db.scalars(select(CreditCard).where(CreditCard.user_id == user_id).order_by(CreditCard.name.asc())))
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="transactions/cards.html",
        context={
            **_base_context(
                request,
                plan=plan,
                subpage="cards",
                flash=request.session.pop("flash_message", None),
            ),
            "cards": cards,
        },
    )


@router.get("/app/transactions/installments")
def installments_page(
    request: Request,
    month: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx
    selected_month = parse_year_month(month, default=date.today())
    cards = list(db.scalars(select(CreditCard).where(CreditCard.user_id == user_id).order_by(CreditCard.name.asc())))
    expense_categories = list(
        db.scalars(
            select(Category)
            .where(Category.user_id == user_id, Category.kind == CategoryKind.EXPENSE)
            .order_by(Category.name.asc())
        )
    )
    installments = list(
        db.scalars(
            select(Installment)
            .join(PlanInstallment, PlanInstallment.installment_id == Installment.id)
            .where(Installment.user_id == user_id, PlanInstallment.plan_id == plan.id)
            .order_by(Installment.created_at.desc())
        )
    )
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="transactions/installments.html",
        context={
            **_base_context(
                request,
                plan=plan,
                subpage="installments",
                flash=request.session.pop("flash_message", None),
            ),
            "selected_month": selected_month,
            "cards": cards,
            "expense_categories": expense_categories,
            "installments": installments,
            "card_name_map": {item.id: item.name for item in cards},
            "category_name_map": {item.id: item.name for item in expense_categories},
        },
    )


@router.get("/app/transactions/recurrences")
def recurrences_page(
    request: Request,
    month: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx
    selected_month = parse_year_month(month, default=date.today())
    accounts = list(db.scalars(select(Account).where(Account.user_id == user_id).order_by(Account.name.asc())))
    categories = list(
        db.scalars(
            select(Category).where(Category.user_id == user_id).order_by(Category.kind.asc(), Category.name.asc())
        )
    )
    recurring_rules = list(
        db.scalars(
            select(RecurringRule)
            .join(PlanRecurringRule, PlanRecurringRule.recurring_rule_id == RecurringRule.id)
            .where(RecurringRule.user_id == user_id, PlanRecurringRule.plan_id == plan.id)
            .order_by(RecurringRule.created_at.desc())
        )
    )
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="transactions/recurrences.html",
        context={
            **_base_context(
                request,
                plan=plan,
                subpage="recurrences",
                flash=request.session.pop("flash_message", None),
            ),
            "selected_month": selected_month,
            "accounts": accounts,
            "categories": categories,
            "recurring_rules": recurring_rules,
            "account_name_map": {item.id: item.name for item in accounts},
            "category_name_map": {item.id: item.name for item in categories},
        },
    )


@router.post("/app/accounts")
def create_account_form(
    request: Request,
    name: str = Form(...),
    account_type: str = Form(...),
    initial_balance: str = Form("0"),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, _ = session_ctx
    validate_csrf(request, csrf_token)
    try:
        db.add(
            Account(
                user_id=user_id,
                name=name.strip(),
                type=AccountType(account_type),
                initial_balance_cents=_signed_money_to_cents(initial_balance),
            )
        )
        db.commit()
        _set_flash(request, kind="ok", message="Conta criada com sucesso.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao criar conta: {exc}")
    return RedirectResponse("/app/transactions/accounts", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/accounts/{account_id}/update")
def update_account_form(
    account_id: UUID,
    request: Request,
    name: str = Form(...),
    account_type: str = Form(...),
    initial_balance: str = Form("0"),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, _ = session_ctx
    validate_csrf(request, csrf_token)
    try:
        row = db.get(Account, account_id)
        if row is None or row.user_id != user_id:
            raise ValueError("Conta nao encontrada.")
        row.name = name.strip()
        row.type = AccountType(account_type)
        row.initial_balance_cents = _signed_money_to_cents(initial_balance)
        db.add(row)
        db.commit()
        _set_flash(request, kind="ok", message="Conta atualizada.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao atualizar conta: {exc}")
    return RedirectResponse("/app/transactions/accounts", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/accounts/{account_id}/delete")
def delete_account_form(
    account_id: UUID,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, _ = session_ctx
    validate_csrf(request, csrf_token)
    try:
        row = db.get(Account, account_id)
        if row is None or row.user_id != user_id:
            raise ValueError("Conta nao encontrada.")
        db.delete(row)
        db.commit()
        _set_flash(request, kind="ok", message="Conta removida.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao remover conta: {exc}")
    return RedirectResponse("/app/transactions/accounts", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/categories")
def create_category_form(
    request: Request,
    name: str = Form(...),
    kind: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, _ = session_ctx
    validate_csrf(request, csrf_token)
    try:
        db.add(Category(user_id=user_id, name=name.strip(), kind=CategoryKind(kind)))
        db.commit()
        _set_flash(request, kind="ok", message="Categoria criada com sucesso.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao criar categoria: {exc}")
    return RedirectResponse("/app/transactions/categories", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/categories/{category_id}/update")
def update_category_form(
    category_id: UUID,
    request: Request,
    name: str = Form(...),
    kind: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, _ = session_ctx
    validate_csrf(request, csrf_token)
    try:
        row = db.get(Category, category_id)
        if row is None or row.user_id != user_id:
            raise ValueError("Categoria nao encontrada.")
        row.name = name.strip()
        row.kind = CategoryKind(kind)
        db.add(row)
        db.commit()
        _set_flash(request, kind="ok", message="Categoria atualizada.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao atualizar categoria: {exc}")
    return RedirectResponse("/app/transactions/categories", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/categories/{category_id}/delete")
def delete_category_form(
    category_id: UUID,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, _ = session_ctx
    validate_csrf(request, csrf_token)
    try:
        row = db.get(Category, category_id)
        if row is None or row.user_id != user_id:
            raise ValueError("Categoria nao encontrada.")
        db.delete(row)
        db.commit()
        _set_flash(request, kind="ok", message="Categoria removida.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao remover categoria: {exc}")
    return RedirectResponse("/app/transactions/categories", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/credit-cards")
def create_credit_card_form(
    request: Request,
    name: str = Form(...),
    closing_day: int = Form(...),
    due_day: int = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, _ = session_ctx
    validate_csrf(request, csrf_token)
    try:
        if not (1 <= closing_day <= 31 and 1 <= due_day <= 31):
            raise ValueError("Dias de fechamento e vencimento devem estar entre 1 e 31.")
        db.add(CreditCard(user_id=user_id, name=name.strip(), closing_day=closing_day, due_day=due_day))
        db.commit()
        _set_flash(request, kind="ok", message="Cartao criado com sucesso.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao criar cartao: {exc}")
    return RedirectResponse("/app/transactions/cards", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/credit-cards/{card_id}/update")
def update_credit_card_form(
    card_id: UUID,
    request: Request,
    name: str = Form(...),
    closing_day: int = Form(...),
    due_day: int = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, _ = session_ctx
    validate_csrf(request, csrf_token)
    try:
        row = db.get(CreditCard, card_id)
        if row is None or row.user_id != user_id:
            raise ValueError("Cartao nao encontrado.")
        if not (1 <= closing_day <= 31 and 1 <= due_day <= 31):
            raise ValueError("Dias de fechamento e vencimento devem estar entre 1 e 31.")
        row.name = name.strip()
        row.closing_day = closing_day
        row.due_day = due_day
        db.add(row)
        db.commit()
        _set_flash(request, kind="ok", message="Cartao atualizado.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao atualizar cartao: {exc}")
    return RedirectResponse("/app/transactions/cards", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/credit-cards/{card_id}/delete")
def delete_credit_card_form(
    card_id: UUID,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, _ = session_ctx
    validate_csrf(request, csrf_token)
    try:
        row = db.get(CreditCard, card_id)
        if row is None or row.user_id != user_id:
            raise ValueError("Cartao nao encontrado.")
        db.delete(row)
        db.commit()
        _set_flash(request, kind="ok", message="Cartao removido.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao remover cartao: {exc}")
    return RedirectResponse("/app/transactions/cards", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/transactions/new")
def create_transaction_form(
    request: Request,
    account_id: UUID = Form(...),
    category_id: UUID = Form(...),
    description: str = Form(""),
    amount: str = Form(...),
    direction: str = Form(...),
    occurred_on: date = Form(...),
    competency_month: str = Form(...),
    is_monthly_recurring: str | None = Form(default=None),
    recurring_end_month: str | None = Form(default=None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx
    validate_csrf(request, csrf_token)
    try:
        account = db.get(Account, account_id)
        category = db.get(Category, category_id)
        if account is None or account.user_id != user_id:
            raise ValueError("Conta invalida.")
        if category is None or category.user_id != user_id:
            raise ValueError("Categoria invalida.")
        direction_enum = TransactionDirection(direction)
        if direction_enum == TransactionDirection.INCOME and category.kind != CategoryKind.INCOME:
            raise ValueError("Categoria de receita obrigatoria para entrada.")
        if direction_enum == TransactionDirection.EXPENSE and category.kind != CategoryKind.EXPENSE:
            raise ValueError("Categoria de despesa obrigatoria para saida.")

        description_value = description.strip() or None
        amount_cents = _money_to_cents(amount)
        competency_month_value = _month_from_input(competency_month)
        payload = CreateTransactionDTO(
            account_id=account_id,
            category_id=category_id,
            description=description_value,
            amount_cents=amount_cents,
            direction=direction_enum,
            occurred_on=occurred_on,
            competency_month=competency_month_value,
            is_recurring_instance=False,
        )
        created = CreateTransactionUseCase(SQLAlchemyTransactionRepository(db)).execute(
            user_id=user_id,
            payload=payload,
        )
        try:
            db.add(PlanTransaction(plan_id=plan.id, transaction_id=created.id))
            db.commit()
        except Exception as exc:
            db.rollback()
            created_row = db.get(Transaction, created.id)
            if created_row is not None:
                db.delete(created_row)
                db.commit()
            raise ValueError(f"Falha ao vincular transacao ao planejamento: {exc}") from exc

        if _is_checked(is_monthly_recurring):
            recurring_start = Month.from_any_date(competency_month_value).add_months(1).value
            recurring_end = _month_from_optional_input(recurring_end_month)
            if recurring_end is not None and recurring_end < recurring_start:
                raise ValueError("Mes final da recorrencia deve ser maior ou igual ao mes seguinte ao lancamento.")
            rule = RecurringRule(
                user_id=user_id,
                name=description_value or "Lancamento recorrente",
                amount_cents=amount_cents,
                direction=direction_enum,
                category_id=category_id,
                account_id=account_id,
                cadence=RecurringCadence.MONTHLY,
                day_of_month=occurred_on.day,
                start_month=recurring_start,
                end_month=recurring_end,
            )
            db.add(rule)
            db.flush()
            db.add(PlanRecurringRule(plan_id=plan.id, recurring_rule_id=rule.id))
            db.commit()
            _set_flash(request, kind="ok", message="Lancamento e recorrencia mensal cadastrados.")
        else:
            _set_flash(request, kind="ok", message="Transacao cadastrada.")

        return RedirectResponse(
            f"/app/transactions?month={competency_month_value.strftime('%Y-%m')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao cadastrar transacao: {exc}")
        return RedirectResponse("/app/transactions", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/transactions/{transaction_id}/edit")
def update_transaction_form(
    transaction_id: UUID,
    request: Request,
    account_id: UUID = Form(...),
    category_id: UUID = Form(...),
    description: str = Form(""),
    amount: str = Form(...),
    direction: str = Form(...),
    occurred_on: date = Form(...),
    competency_month: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx
    validate_csrf(request, csrf_token)
    try:
        row = db.scalar(
            select(Transaction)
            .join(PlanTransaction, PlanTransaction.transaction_id == Transaction.id)
            .where(
                Transaction.id == transaction_id,
                Transaction.user_id == user_id,
                PlanTransaction.plan_id == plan.id,
            )
        )
        if row is None:
            raise ValueError("Transacao nao encontrada no planejamento ativo.")
        account = db.get(Account, account_id)
        category = db.get(Category, category_id)
        if account is None or account.user_id != user_id:
            raise ValueError("Conta invalida.")
        if category is None or category.user_id != user_id:
            raise ValueError("Categoria invalida.")
        direction_enum = TransactionDirection(direction)
        if direction_enum == TransactionDirection.INCOME and category.kind != CategoryKind.INCOME:
            raise ValueError("Categoria de receita obrigatoria para entrada.")
        if direction_enum == TransactionDirection.EXPENSE and category.kind != CategoryKind.EXPENSE:
            raise ValueError("Categoria de despesa obrigatoria para saida.")
        competency_month_value = _month_from_input(competency_month)
        row.account_id = account_id
        row.category_id = category_id
        row.description = description.strip() or None
        row.amount_cents = _money_to_cents(amount)
        row.direction = direction_enum
        row.occurred_on = occurred_on
        row.competency_month = competency_month_value
        db.add(row)
        db.commit()
        _set_flash(request, kind="ok", message="Transacao atualizada.")
        return RedirectResponse(
            f"/app/transactions?month={competency_month_value.strftime('%Y-%m')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao atualizar transacao: {exc}")
        return RedirectResponse("/app/transactions", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/transactions/{transaction_id}/delete")
def delete_transaction_form(
    transaction_id: UUID,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx
    validate_csrf(request, csrf_token)
    try:
        mapping = db.scalar(
            select(PlanTransaction).where(
                PlanTransaction.plan_id == plan.id,
                PlanTransaction.transaction_id == transaction_id,
            )
        )
        row = db.get(Transaction, transaction_id)
        if mapping is None or row is None or row.user_id != user_id:
            raise ValueError("Transacao nao encontrada no planejamento ativo.")
        db.delete(mapping)
        db.delete(row)
        db.commit()
        _set_flash(request, kind="ok", message="Transacao removida.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao remover transacao: {exc}")
    return RedirectResponse("/app/transactions", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/installments")
def create_installment_form(
    request: Request,
    credit_card_id: UUID = Form(...),
    category_id: UUID = Form(...),
    description: str = Form(""),
    total_parts: int = Form(...),
    part_amount: str = Form(...),
    first_competency_month: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx
    validate_csrf(request, csrf_token)
    try:
        card = db.get(CreditCard, credit_card_id)
        category = db.get(Category, category_id)
        if card is None or card.user_id != user_id:
            raise ValueError("Cartao invalido.")
        if category is None or category.user_id != user_id:
            raise ValueError("Categoria invalida.")
        if category.kind != CategoryKind.EXPENSE:
            raise ValueError("Parcelamento deve usar categoria de despesa.")
        if total_parts <= 0:
            raise ValueError("Numero de parcelas deve ser maior que zero.")
        row = Installment(
            user_id=user_id,
            credit_card_id=credit_card_id,
            category_id=category_id,
            description=description.strip() or None,
            total_parts=total_parts,
            part_amount_cents=_money_to_cents(part_amount),
            first_competency_month=_month_from_input(first_competency_month),
        )
        db.add(row)
        db.flush()
        db.add(PlanInstallment(plan_id=plan.id, installment_id=row.id))
        db.commit()
        _set_flash(request, kind="ok", message="Parcelamento criado com sucesso.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao criar parcelamento: {exc}")
    return RedirectResponse("/app/transactions/installments", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/installments/{installment_id}/update")
def update_installment_form(
    installment_id: UUID,
    request: Request,
    credit_card_id: UUID = Form(...),
    category_id: UUID = Form(...),
    description: str = Form(""),
    total_parts: int = Form(...),
    part_amount: str = Form(...),
    first_competency_month: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx
    validate_csrf(request, csrf_token)
    try:
        row = db.scalar(
            select(Installment)
            .join(PlanInstallment, PlanInstallment.installment_id == Installment.id)
            .where(
                Installment.id == installment_id,
                Installment.user_id == user_id,
                PlanInstallment.plan_id == plan.id,
            )
        )
        if row is None:
            raise ValueError("Parcelamento nao encontrado no planejamento ativo.")
        card = db.get(CreditCard, credit_card_id)
        category = db.get(Category, category_id)
        if card is None or card.user_id != user_id:
            raise ValueError("Cartao invalido.")
        if category is None or category.user_id != user_id:
            raise ValueError("Categoria invalida.")
        if category.kind != CategoryKind.EXPENSE:
            raise ValueError("Parcelamento deve usar categoria de despesa.")
        if total_parts <= 0:
            raise ValueError("Numero de parcelas deve ser maior que zero.")
        row.credit_card_id = credit_card_id
        row.category_id = category_id
        row.description = description.strip() or None
        row.total_parts = total_parts
        row.part_amount_cents = _money_to_cents(part_amount)
        row.first_competency_month = _month_from_input(first_competency_month)
        db.add(row)
        db.commit()
        _set_flash(request, kind="ok", message="Parcelamento atualizado.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao atualizar parcelamento: {exc}")
    return RedirectResponse("/app/transactions/installments", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/installments/{installment_id}/delete")
def delete_installment_form(
    installment_id: UUID,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx
    validate_csrf(request, csrf_token)
    try:
        mapping = db.scalar(
            select(PlanInstallment).where(
                PlanInstallment.plan_id == plan.id,
                PlanInstallment.installment_id == installment_id,
            )
        )
        row = db.get(Installment, installment_id)
        if mapping is None or row is None or row.user_id != user_id:
            raise ValueError("Parcelamento nao encontrado no planejamento ativo.")
        db.delete(mapping)
        db.delete(row)
        db.commit()
        _set_flash(request, kind="ok", message="Parcelamento removido.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao remover parcelamento: {exc}")
    return RedirectResponse("/app/transactions/installments", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/recurring-rules")
def create_recurring_rule_form(
    request: Request,
    name: str = Form(...),
    account_id: UUID = Form(...),
    category_id: UUID = Form(...),
    direction: str = Form(...),
    amount: str = Form(...),
    day_of_month: int = Form(...),
    start_month: str = Form(...),
    end_month: str | None = Form(default=None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx
    validate_csrf(request, csrf_token)
    try:
        account = db.get(Account, account_id)
        category = db.get(Category, category_id)
        if account is None or account.user_id != user_id:
            raise ValueError("Conta invalida.")
        if category is None or category.user_id != user_id:
            raise ValueError("Categoria invalida.")
        direction_enum = TransactionDirection(direction)
        if direction_enum == TransactionDirection.INCOME and category.kind != CategoryKind.INCOME:
            raise ValueError("Categoria de receita obrigatoria para entrada.")
        if direction_enum == TransactionDirection.EXPENSE and category.kind != CategoryKind.EXPENSE:
            raise ValueError("Categoria de despesa obrigatoria para saida.")
        if not (1 <= day_of_month <= 31):
            raise ValueError("Dia do mes deve estar entre 1 e 31.")
        start_value = _month_from_input(start_month)
        end_value = _month_from_optional_input(end_month)
        if end_value is not None and end_value < start_value:
            raise ValueError("Mes final deve ser maior ou igual ao mes inicial.")
        row = RecurringRule(
            user_id=user_id,
            name=name.strip() or "Lancamento recorrente",
            amount_cents=_money_to_cents(amount),
            direction=direction_enum,
            category_id=category_id,
            account_id=account_id,
            cadence=RecurringCadence.MONTHLY,
            day_of_month=day_of_month,
            start_month=start_value,
            end_month=end_value,
        )
        db.add(row)
        db.flush()
        db.add(PlanRecurringRule(plan_id=plan.id, recurring_rule_id=row.id))
        db.commit()
        _set_flash(request, kind="ok", message="Recorrencia criada com sucesso.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao criar recorrencia: {exc}")
    return RedirectResponse("/app/transactions/recurrences", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/recurring-rules/{rule_id}/update")
def update_recurring_rule_form(
    rule_id: UUID,
    request: Request,
    name: str = Form(...),
    account_id: UUID = Form(...),
    category_id: UUID = Form(...),
    direction: str = Form(...),
    amount: str = Form(...),
    day_of_month: int = Form(...),
    start_month: str = Form(...),
    end_month: str | None = Form(default=None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx
    validate_csrf(request, csrf_token)
    try:
        row = db.scalar(
            select(RecurringRule)
            .join(PlanRecurringRule, PlanRecurringRule.recurring_rule_id == RecurringRule.id)
            .where(
                RecurringRule.id == rule_id,
                RecurringRule.user_id == user_id,
                PlanRecurringRule.plan_id == plan.id,
            )
        )
        if row is None:
            raise ValueError("Recorrencia nao encontrada no planejamento ativo.")
        account = db.get(Account, account_id)
        category = db.get(Category, category_id)
        if account is None or account.user_id != user_id:
            raise ValueError("Conta invalida.")
        if category is None or category.user_id != user_id:
            raise ValueError("Categoria invalida.")
        direction_enum = TransactionDirection(direction)
        if direction_enum == TransactionDirection.INCOME and category.kind != CategoryKind.INCOME:
            raise ValueError("Categoria de receita obrigatoria para entrada.")
        if direction_enum == TransactionDirection.EXPENSE and category.kind != CategoryKind.EXPENSE:
            raise ValueError("Categoria de despesa obrigatoria para saida.")
        if not (1 <= day_of_month <= 31):
            raise ValueError("Dia do mes deve estar entre 1 e 31.")
        start_value = _month_from_input(start_month)
        end_value = _month_from_optional_input(end_month)
        if end_value is not None and end_value < start_value:
            raise ValueError("Mes final deve ser maior ou igual ao mes inicial.")
        row.name = name.strip() or "Lancamento recorrente"
        row.account_id = account_id
        row.category_id = category_id
        row.direction = direction_enum
        row.amount_cents = _money_to_cents(amount)
        row.day_of_month = day_of_month
        row.start_month = start_value
        row.end_month = end_value
        row.cadence = RecurringCadence.MONTHLY
        db.add(row)
        db.commit()
        _set_flash(request, kind="ok", message="Recorrencia atualizada.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao atualizar recorrencia: {exc}")
    return RedirectResponse("/app/transactions/recurrences", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/recurring-rules/{rule_id}/delete")
def delete_recurring_rule_form(
    rule_id: UUID,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx
    validate_csrf(request, csrf_token)
    try:
        mapping = db.scalar(
            select(PlanRecurringRule).where(
                PlanRecurringRule.plan_id == plan.id,
                PlanRecurringRule.recurring_rule_id == rule_id,
            )
        )
        row = db.get(RecurringRule, rule_id)
        if mapping is None or row is None or row.user_id != user_id:
            raise ValueError("Recorrencia nao encontrada no planejamento ativo.")
        db.delete(mapping)
        db.delete(row)
        db.commit()
        _set_flash(request, kind="ok", message="Recorrencia removida.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao remover recorrencia: {exc}")
    return RedirectResponse("/app/transactions/recurrences", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/api/transactions", response_model=TransactionReadDTO, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: CreateTransactionDTO,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return CreateTransactionUseCase(SQLAlchemyTransactionRepository(db)).execute(
        user_id=user_id,
        payload=payload,
    )


@router.put("/api/transactions/{transaction_id}", response_model=TransactionReadDTO)
def update_transaction(
    transaction_id: UUID,
    payload: UpdateTransactionDTO,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        return UpdateTransactionUseCase(SQLAlchemyTransactionRepository(db)).execute(
            user_id=user_id,
            transaction_id=transaction_id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/api/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    transaction_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        SQLAlchemyTransactionRepository(db).delete(user_id=user_id, transaction_id=transaction_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return None
