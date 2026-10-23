import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.services.debt_payoff import DebtSnapshot, simulate_debt_payoff
from app.domain.value_objects.month import Month
from app.infrastructure.auth.csrf import get_or_create_csrf_token, validate_csrf
from app.infrastructure.db.models.account import Account
from app.infrastructure.db.models.category import Category
from app.infrastructure.db.models.category_budget import CategoryBudget
from app.infrastructure.db.models.debt import Debt
from app.infrastructure.db.models.debt_plan import DebtPlan
from app.infrastructure.db.models.enums import DebtKind, TransactionDirection
from app.infrastructure.db.models.financial_goal import FinancialGoal
from app.infrastructure.db.models.financial_plan import FinancialPlan
from app.infrastructure.db.models.income_opportunity import IncomeOpportunity
from app.infrastructure.db.models.mileage_movement import MileageMovement
from app.infrastructure.db.models.mileage_program import MileageProgram
from app.infrastructure.db.models.recurring_rule import RecurringRule
from app.infrastructure.db.models.transaction import Transaction
from app.infrastructure.db.session import get_db
from app.web.routers._utils import plan_id_from_session, user_id_from_session

router = APIRouter()

DEBT_KIND_LABELS = {
    DebtKind.TAX: "Imposto / governo",
    DebtKind.LOAN: "Financiamento / empréstimo",
    DebtKind.CREDIT: "Cartão / crédito",
    DebtKind.OTHER: "Outra dívida",
}
GOAL_LABELS = {
    "EMERGENCY": "Reserva de emergência",
    "DEBT_FREE": "Liberdade de dívidas",
    "EDUCATION": "Educação",
    "HOME": "Casa / patrimônio",
    "TRAVEL": "Experiências",
    "INVESTMENT": "Investimentos",
    "OTHER": "Outro objetivo",
}
STAGE_LABELS = {
    "IDEA": "Ideia",
    "VALIDATING": "Validando",
    "ACTIVE": "Em execução",
    "GENERATING": "Gerando renda",
    "PAUSED": "Pausada",
}
MILEAGE_MOVEMENT_LABELS = {
    "EARN": "Acúmulo",
    "REDEEM": "Resgate",
    "ADJUSTMENT": "Ajuste",
}


def _money(value: str, *, allow_zero: bool = True) -> int:
    try:
        normalized = value.strip()
        if "," in normalized and "." in normalized:
            normalized = normalized.replace(".", "").replace(",", ".")
        elif "," in normalized:
            normalized = normalized.replace(",", ".")
        parsed = Decimal(normalized or "0")
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("Valor monetário inválido.") from exc
    cents = int((parsed * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if cents < 0 or (not allow_zero and cents == 0):
        raise ValueError("O valor precisa ser maior que zero.")
    return cents


def _optional_date(value: str) -> date | None:
    return date.fromisoformat(value) if value.strip() else None


def _miles(value: str, *, allow_zero: bool = True, allow_negative: bool = False) -> int:
    normalized = (value or "").strip().replace(".", "").replace(" ", "")
    normalized = normalized.removeprefix("+")
    try:
        miles = int(normalized or "0")
    except ValueError as exc:
        raise ValueError("Quantidade de milhas inválida.") from exc
    if (not allow_negative and miles < 0) or (not allow_zero and miles == 0):
        raise ValueError("Informe uma quantidade de milhas válida.")
    return miles


def _flash(request: Request, kind: str, message: str) -> None:
    request.session["prosperity_flash"] = {"kind": kind, "message": message}


def _active_plan(db: Session, request: Request, user_id: UUID) -> FinancialPlan | None:
    plan_id = plan_id_from_session(request)
    if plan_id is None:
        return None
    return db.scalar(
        select(FinancialPlan).where(
            FinancialPlan.id == plan_id, FinancialPlan.user_id == user_id
        )
    )


def _merchant_key(description: str | None) -> str:
    text = (description or "Sem descrição").upper()
    text = re.sub(r"\b\d{1,2}[/-]\d{1,2}\b", "", text)
    text = re.sub(r"\d+", "", text)
    text = re.sub(r"[^A-ZÀ-Ú ]", " ", text)
    return " ".join(text.split())[:44] or "SEM DESCRIÇÃO"


@router.get("/app/prosperity")
def prosperity_page(
    request: Request,
    extra_budget: str = Query(default="0"),
    db: Session = Depends(get_db),
):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    plan = _active_plan(db, request, user_id)
    debts = list(
        db.scalars(
            select(Debt)
            .where(Debt.user_id == user_id)
            .order_by(Debt.status, Debt.current_balance_cents.desc())
        )
    )
    goals = list(
        db.scalars(
            select(FinancialGoal)
            .where(FinancialGoal.user_id == user_id)
            .order_by(
                FinancialGoal.status, FinancialGoal.priority, FinancialGoal.created_at
            )
        )
    )
    opportunities = list(
        db.scalars(
            select(IncomeOpportunity)
            .where(IncomeOpportunity.user_id == user_id)
            .order_by(IncomeOpportunity.stage, IncomeOpportunity.created_at.desc())
        )
    )
    mileage_programs = list(
        db.scalars(
            select(MileageProgram)
            .where(MileageProgram.user_id == user_id)
            .order_by(
                MileageProgram.expires_on.is_(None),
                MileageProgram.expires_on,
                MileageProgram.name,
            )
        )
    )
    mileage_movements = list(
        db.scalars(
            select(MileageMovement)
            .where(MileageMovement.user_id == user_id)
            .order_by(
                MileageMovement.occurred_on.desc(), MileageMovement.created_at.desc()
            )
            .limit(8)
        )
    )
    mileage_expiry_limit = date.today() + timedelta(days=90)
    expiring_mileage_programs = [
        item
        for item in mileage_programs
        if item.balance_miles > 0
        and item.expires_on is not None
        and item.expires_on <= mileage_expiry_limit
    ]
    expense_categories = list(
        db.scalars(
            select(Category)
            .where(Category.user_id == user_id, Category.kind == "EXPENSE")
            .order_by(Category.name)
        )
    )
    budgets = list(
        db.scalars(
            select(CategoryBudget).where(
                CategoryBudget.user_id == user_id,
                CategoryBudget.is_active.is_(True),
            )
        )
    )
    plans_by_debt = {
        item.debt_id: item
        for item in db.scalars(select(DebtPlan).where(DebtPlan.user_id == user_id))
    }

    try:
        extra_cents = _money(extra_budget)
    except ValueError:
        extra_cents = 0
    snapshots = [
        DebtSnapshot(
            id=str(item.id),
            name=item.name,
            balance_cents=item.current_balance_cents,
            minimum_payment_cents=max(
                item.minimum_payment_cents,
                plans_by_debt.get(item.id).monthly_payment_cents
                if plans_by_debt.get(item.id)
                else 0,
            ),
            interest_apr_bps=item.interest_apr_bps or 0,
        )
        for item in debts
        if item.status == "ACTIVE" and item.current_balance_cents > 0
    ]
    avalanche = simulate_debt_payoff(
        snapshots,
        extra_monthly_cents=extra_cents,
        strategy="AVALANCHE",
        start_month=date.today(),
    )
    snowball = simulate_debt_payoff(
        snapshots,
        extra_monthly_cents=extra_cents,
        strategy="SNOWBALL",
        start_month=date.today(),
    )

    six_months_ago = Month.from_any_date(date.today()).add_months(-5).value
    tx_rows = list(
        db.execute(
            select(Transaction, Category)
            .join(Category, Category.id == Transaction.category_id)
            .where(
                Transaction.user_id == user_id,
                Transaction.direction == TransactionDirection.EXPENSE,
                Transaction.competency_month >= six_months_ago,
            )
        )
    )
    category_totals: dict[str, int] = defaultdict(int)
    merchants: dict[str, dict[str, object]] = {}
    for tx, category in tx_rows:
        category_totals[category.name] += tx.amount_cents
        key = _merchant_key(tx.description)
        row = merchants.setdefault(
            key, {"name": key.title(), "total": 0, "count": 0, "months": set()}
        )
        row["total"] = int(row["total"]) + tx.amount_cents
        row["count"] = int(row["count"]) + 1
        months = row["months"]
        assert isinstance(months, set)
        months.add(tx.competency_month)
    top_categories = sorted(
        category_totals.items(), key=lambda item: item[1], reverse=True
    )[:6]
    recurring_candidates = sorted(
        [row for row in merchants.values() if len(row["months"]) >= 2],
        key=lambda item: (len(item["months"]), int(item["total"])),
        reverse=True,
    )[:8]
    for item in recurring_candidates:
        item["month_count"] = len(item.pop("months"))
        item["average"] = round(int(item["total"]) / int(item["count"]))

    current_month = Month.from_any_date(date.today()).value
    next_month = Month.from_any_date(current_month).add_months(1).value
    current_spending = {
        category_id: int(total)
        for category_id, total in db.execute(
            select(
                Transaction.category_id,
                func.coalesce(func.sum(Transaction.amount_cents), 0),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.direction == TransactionDirection.EXPENSE,
                Transaction.competency_month >= current_month,
                Transaction.competency_month < next_month,
            )
            .group_by(Transaction.category_id)
        )
    }
    categories_by_id = {item.id: item for item in expense_categories}
    budget_cards: list[dict[str, object]] = []
    for budget in budgets:
        category = categories_by_id.get(budget.category_id)
        if category is None:
            continue
        spent = current_spending.get(budget.category_id, 0)
        percent = (
            round(spent / budget.monthly_limit_cents * 100)
            if budget.monthly_limit_cents
            else 0
        )
        budget_cards.append(
            {
                "category": category,
                "budget": budget,
                "spent_cents": spent,
                "remaining_cents": budget.monthly_limit_cents - spent,
                "percent": percent,
                "bar_percent": min(100, percent),
                "tone": "rose"
                if percent >= 100
                else "amber"
                if percent >= budget.alert_percent
                else "emerald",
            }
        )
    budget_cards.sort(key=lambda item: int(item["percent"]), reverse=True)

    account_count = (
        db.scalar(
            select(func.count()).select_from(Account).where(Account.user_id == user_id)
        )
        or 0
    )
    recurring_income = (
        db.scalar(
            select(func.coalesce(func.sum(RecurringRule.amount_cents), 0)).where(
                RecurringRule.user_id == user_id,
                RecurringRule.direction == TransactionDirection.INCOME,
            )
        )
        or 0
    )
    readiness_items = [
        ("Contas cadastradas", account_count > 0),
        ("Renda recorrente mapeada", recurring_income > 0),
        ("Orçamento por categoria definido", len(budgets) > 0),
        ("Dívidas inventariadas", len(debts) > 0),
        ("Meta de prosperidade criada", len(goals) > 0),
        (
            "Oportunidade de renda em ação",
            any(item.stage in {"ACTIVE", "GENERATING"} for item in opportunities),
        ),
    ]
    readiness_score = round(
        sum(1 for _, ready in readiness_items if ready) / len(readiness_items) * 100
    )
    next_focus = next(
        (label for label, ready in readiness_items if not ready),
        "Revisar e evoluir o plano",
    )

    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="prosperity/index.html",
        context={
            "active_page": "prosperity",
            "current_plan_name": plan.name if plan else None,
            "csrf_token": get_or_create_csrf_token(request),
            "flash": request.session.pop("prosperity_flash", None),
            "debts": debts,
            "debt_plans": plans_by_debt,
            "goals": goals,
            "opportunities": opportunities,
            "mileage_programs": mileage_programs,
            "mileage_programs_by_id": {item.id: item for item in mileage_programs},
            "mileage_movements": mileage_movements,
            "mileage_movement_labels": MILEAGE_MOVEMENT_LABELS,
            "mileage_movement_kinds": [
                {"value": value, "label": label}
                for value, label in MILEAGE_MOVEMENT_LABELS.items()
            ],
            "total_miles": sum(item.balance_miles for item in mileage_programs),
            "expiring_miles": sum(
                item.balance_miles for item in expiring_mileage_programs
            ),
            "mileage_expiry_limit": mileage_expiry_limit,
            "debt_kind_labels": {
                key.value: value for key, value in DEBT_KIND_LABELS.items()
            },
            "debt_kinds": [
                {"value": key.value, "label": value}
                for key, value in DEBT_KIND_LABELS.items()
            ],
            "goal_labels": GOAL_LABELS,
            "stage_labels": STAGE_LABELS,
            "extra_budget_cents": extra_cents,
            "avalanche": avalanche,
            "snowball": snowball,
            "total_debt_cents": sum(
                item.current_balance_cents for item in debts if item.status == "ACTIVE"
            ),
            "minimum_commitment_cents": sum(
                item.minimum_payment_cents for item in debts if item.status == "ACTIVE"
            ),
            "goal_target_cents": sum(
                item.target_cents for item in goals if item.status == "ACTIVE"
            ),
            "goal_current_cents": sum(
                item.current_cents for item in goals if item.status == "ACTIVE"
            ),
            "income_potential_cents": sum(
                item.expected_monthly_cents
                for item in opportunities
                if item.stage not in {"PAUSED"}
            ),
            "top_categories": top_categories,
            "recurring_candidates": recurring_candidates,
            "expense_categories": expense_categories,
            "budget_cards": budget_cards,
            "current_month": current_month,
            "readiness_items": readiness_items,
            "readiness_score": readiness_score,
            "next_focus": next_focus,
            "today": date.today(),
        },
    )


@router.post("/app/prosperity/budgets")
def upsert_budget(
    request: Request,
    category_id: UUID = Form(...),
    monthly_limit: str = Form(...),
    alert_percent: int = Form(80),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=303)
    validate_csrf(request, csrf_token)
    try:
        category = db.scalar(
            select(Category).where(
                Category.id == category_id,
                Category.user_id == user_id,
                Category.kind == "EXPENSE",
            )
        )
        if category is None:
            raise ValueError("Categoria de despesa inválida.")
        limit_cents = _money(monthly_limit, allow_zero=False)
        budget = db.scalar(
            select(CategoryBudget).where(
                CategoryBudget.user_id == user_id,
                CategoryBudget.category_id == category_id,
            )
        )
        if budget is None:
            budget = CategoryBudget(
                user_id=user_id,
                category_id=category_id,
                monthly_limit_cents=limit_cents,
            )
        budget.monthly_limit_cents = limit_cents
        budget.alert_percent = max(1, min(100, alert_percent))
        budget.is_active = True
        db.add(budget)
        db.commit()
        _flash(request, "ok", f"Orçamento de {category.name} atualizado.")
    except Exception as exc:
        db.rollback()
        _flash(request, "error", f"Não foi possível salvar o orçamento: {exc}")
    return RedirectResponse("/app/prosperity#orcamento", status_code=303)


@router.post("/app/prosperity/debts")
def create_debt(
    request: Request,
    name: str = Form(...),
    creditor: str = Form(""),
    kind: DebtKind = Form(...),
    current_balance: str = Form(...),
    minimum_payment: str = Form("0"),
    interest_apr: str = Form("0"),
    due_day: int | None = Form(None),
    notes: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=303)
    validate_csrf(request, csrf_token)
    try:
        balance = _money(current_balance, allow_zero=False)
        minimum = _money(minimum_payment)
        apr_bps = int(
            (Decimal(interest_apr.replace(",", ".") or "0") * 100).quantize(Decimal(1))
        )
        if due_day is not None and not 1 <= due_day <= 31:
            raise ValueError("Dia de vencimento inválido.")
        debt = Debt(
            user_id=user_id,
            name=name.strip(),
            creditor=creditor.strip() or None,
            kind=kind,
            principal_cents=balance,
            current_balance_cents=balance,
            minimum_payment_cents=minimum,
            interest_apr_bps=apr_bps,
            start_month=Month.from_any_date(date.today()).value,
            due_day=due_day,
            notes=notes.strip() or None,
            status="ACTIVE",
        )
        db.add(debt)
        db.flush()
        if minimum > 0:
            db.add(
                DebtPlan(
                    debt_id=debt.id,
                    user_id=user_id,
                    monthly_payment_cents=minimum,
                    start_month=Month.from_any_date(date.today()).value,
                    end_month=None,
                )
            )
        db.commit()
        _flash(request, "ok", "Dívida adicionada ao mapa de quitação.")
    except Exception as exc:
        db.rollback()
        _flash(request, "error", f"Não foi possível cadastrar a dívida: {exc}")
    return RedirectResponse("/app/prosperity#dividas", status_code=303)


@router.post("/app/prosperity/debts/{debt_id}/balance")
def update_debt_balance(
    debt_id: UUID,
    request: Request,
    current_balance: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=303)
    validate_csrf(request, csrf_token)
    debt = db.scalar(select(Debt).where(Debt.id == debt_id, Debt.user_id == user_id))
    if debt:
        debt.current_balance_cents = _money(current_balance)
        debt.status = "PAID" if debt.current_balance_cents == 0 else "ACTIVE"
        db.commit()
        _flash(request, "ok", "Saldo da dívida atualizado.")
    return RedirectResponse("/app/prosperity#dividas", status_code=303)


@router.post("/app/prosperity/goals")
def create_goal(
    request: Request,
    name: str = Form(...),
    category: str = Form("OTHER"),
    target: str = Form(...),
    current: str = Form("0"),
    monthly_contribution: str = Form("0"),
    target_date: str = Form(""),
    priority: int = Form(3),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=303)
    validate_csrf(request, csrf_token)
    try:
        db.add(
            FinancialGoal(
                user_id=user_id,
                name=name.strip(),
                category=category,
                target_cents=_money(target, allow_zero=False),
                current_cents=_money(current),
                monthly_contribution_cents=_money(monthly_contribution),
                target_date=_optional_date(target_date),
                priority=max(1, min(5, priority)),
                status="ACTIVE",
            )
        )
        db.commit()
        _flash(request, "ok", "Meta criada. Agora ela faz parte do seu plano.")
    except Exception as exc:
        db.rollback()
        _flash(request, "error", f"Não foi possível criar a meta: {exc}")
    return RedirectResponse("/app/prosperity#metas", status_code=303)


@router.post("/app/prosperity/goals/{goal_id}/contribute")
def contribute_goal(
    goal_id: UUID,
    request: Request,
    amount: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=303)
    validate_csrf(request, csrf_token)
    goal = db.scalar(
        select(FinancialGoal).where(
            FinancialGoal.id == goal_id, FinancialGoal.user_id == user_id
        )
    )
    if goal:
        goal.current_cents = min(
            goal.target_cents, goal.current_cents + _money(amount, allow_zero=False)
        )
        goal.status = (
            "COMPLETED" if goal.current_cents >= goal.target_cents else "ACTIVE"
        )
        db.commit()
        _flash(request, "ok", "Aporte registrado. Progresso atualizado!")
    return RedirectResponse("/app/prosperity#metas", status_code=303)


@router.post("/app/prosperity/opportunities")
def create_opportunity(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    expected_monthly: str = Form("0"),
    setup_cost: str = Form("0"),
    hours_per_week: int = Form(0),
    stage: str = Form("IDEA"),
    next_action: str = Form(""),
    target_date: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=303)
    validate_csrf(request, csrf_token)
    try:
        db.add(
            IncomeOpportunity(
                user_id=user_id,
                title=title.strip(),
                description=description.strip() or None,
                expected_monthly_cents=_money(expected_monthly),
                setup_cost_cents=_money(setup_cost),
                hours_per_week=max(0, hours_per_week),
                stage=stage,
                next_action=next_action.strip() or None,
                target_date=_optional_date(target_date),
            )
        )
        db.commit()
        _flash(request, "ok", "Oportunidade adicionada ao laboratório de renda.")
    except Exception as exc:
        db.rollback()
        _flash(request, "error", f"Não foi possível salvar a oportunidade: {exc}")
    return RedirectResponse("/app/prosperity#renda", status_code=303)


@router.post("/app/prosperity/opportunities/{opportunity_id}/stage")
def update_opportunity_stage(
    opportunity_id: UUID,
    request: Request,
    stage: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=303)
    validate_csrf(request, csrf_token)
    item = db.scalar(
        select(IncomeOpportunity).where(
            IncomeOpportunity.id == opportunity_id, IncomeOpportunity.user_id == user_id
        )
    )
    if item and stage in STAGE_LABELS:
        item.stage = stage
        db.commit()
        _flash(request, "ok", "Etapa da oportunidade atualizada.")
    return RedirectResponse("/app/prosperity#renda", status_code=303)


@router.post("/app/prosperity/miles/programs")
def create_mileage_program(
    request: Request,
    name: str = Form(...),
    balance: str = Form("0"),
    target: str = Form(""),
    expires_on: str = Form(""),
    notes: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=303)
    validate_csrf(request, csrf_token)
    try:
        program_name = name.strip()
        if not program_name:
            raise ValueError("Informe o nome do programa de milhas.")
        target_miles = _miles(target) if target.strip() else None
        db.add(
            MileageProgram(
                user_id=user_id,
                name=program_name,
                balance_miles=_miles(balance),
                target_miles=target_miles,
                expires_on=_optional_date(expires_on),
                notes=notes.strip() or None,
            )
        )
        db.commit()
        _flash(request, "ok", "Programa de milhas adicionado ao seu planejamento.")
    except Exception as exc:
        db.rollback()
        _flash(request, "error", f"Não foi possível salvar o programa: {exc}")
    return RedirectResponse("/app/prosperity#milhas", status_code=303)


@router.post("/app/prosperity/miles/programs/{program_id}/movements")
def add_mileage_movement(
    program_id: UUID,
    request: Request,
    kind: str = Form(...),
    miles: str = Form(...),
    occurred_on: str = Form(...),
    description: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=303)
    validate_csrf(request, csrf_token)
    try:
        program = db.scalar(
            select(MileageProgram).where(
                MileageProgram.id == program_id, MileageProgram.user_id == user_id
            )
        )
        if program is None:
            raise ValueError("Programa de milhas não encontrado.")
        if kind not in MILEAGE_MOVEMENT_LABELS:
            raise ValueError("Tipo de movimentação inválido.")
        if kind == "ADJUSTMENT":
            delta = _miles(miles, allow_zero=False, allow_negative=True)
        else:
            quantity = _miles(miles, allow_zero=False)
            delta = quantity if kind == "EARN" else -quantity
        if program.balance_miles + delta < 0:
            raise ValueError("O resgate não pode deixar o saldo de milhas negativo.")
        movement_date = _optional_date(occurred_on)
        if movement_date is None:
            raise ValueError("Informe a data da movimentação.")
        program.balance_miles += delta
        db.add(
            MileageMovement(
                user_id=user_id,
                program_id=program.id,
                kind=kind,
                miles=delta,
                occurred_on=movement_date,
                description=description.strip() or None,
            )
        )
        db.commit()
        _flash(request, "ok", "Movimentação de milhas registrada.")
    except Exception as exc:
        db.rollback()
        _flash(request, "error", f"Não foi possível registrar a movimentação: {exc}")
    return RedirectResponse("/app/prosperity#milhas", status_code=303)
