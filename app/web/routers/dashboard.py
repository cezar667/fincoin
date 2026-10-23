from datetime import date

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.application.use_cases.build_forecast import BuildForecastUseCase
from app.infrastructure.auth.csrf import get_or_create_csrf_token
from app.infrastructure.db.models.category_budget import CategoryBudget
from app.infrastructure.db.models.debt import Debt
from app.infrastructure.db.models.financial_goal import FinancialGoal
from app.infrastructure.db.models.financial_plan import FinancialPlan
from app.infrastructure.db.models.income_opportunity import IncomeOpportunity
from app.infrastructure.db.session import get_db
from app.infrastructure.repositories.transaction_repo import (
    SQLAlchemyForecastRepository,
)
from app.web.routers._utils import (
    parse_year_month,
    plan_id_from_session,
    user_id_from_session,
)

router = APIRouter(prefix="/app")

MONTH_NAMES = (
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
)


def _month_label(value: date, *, short: bool = False) -> str:
    name = MONTH_NAMES[value.month - 1]
    return f"{name[:3]}" if short else f"{name} de {value.year}"


@router.get("/dashboard")
def dashboard_page(
    request: Request,
    month: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    active_plan_id = plan_id_from_session(request)
    if active_plan_id is None:
        return RedirectResponse("/app/plans", status_code=status.HTTP_303_SEE_OTHER)
    active_plan = db.scalar(
        select(FinancialPlan).where(
            FinancialPlan.id == active_plan_id,
            FinancialPlan.user_id == user_id,
        )
    )
    if active_plan is None:
        request.session.pop("active_plan_id", None)
        return RedirectResponse("/app/plans", status_code=status.HTTP_303_SEE_OTHER)
    selected_month = parse_year_month(month, default=date.today())
    forecast_repository = SQLAlchemyForecastRepository(db)
    forecast = BuildForecastUseCase(forecast_repository).execute(
        user_id=user_id,
        from_month=selected_month,
        months=6,
        plan_id=active_plan.id,
    )
    focus_months = min(2, len(forecast.lines))
    income_details = forecast_repository.build_income_details(
        user_id=user_id,
        from_month=selected_month,
        months=focus_months,
        plan_id=active_plan.id,
    )
    expense_details = forecast_repository.build_expense_details(
        user_id=user_id,
        from_month=selected_month,
        months=focus_months,
        plan_id=active_plan.id,
    )
    focused_months = [
        {
            "line": line,
            "title": _month_label(line.month),
            "income_items": income_details.get(line.month, []),
            "expense_items": expense_details.get(line.month, []),
        }
        for line in forecast.lines[:focus_months]
    ]
    month_rail = [
        {
            "line": line,
            "label": _month_label(line.month, short=True),
            "year": str(line.month.year)[-2:],
            "is_selected": line.month == selected_month,
        }
        for line in forecast.lines
    ]
    total_debt_cents = (
        db.scalar(
            select(func.coalesce(func.sum(Debt.current_balance_cents), 0)).where(
                Debt.user_id == user_id, Debt.status == "ACTIVE"
            )
        )
        or 0
    )
    goal_totals = db.execute(
        select(
            func.coalesce(func.sum(FinancialGoal.current_cents), 0),
            func.coalesce(func.sum(FinancialGoal.target_cents), 0),
        ).where(FinancialGoal.user_id == user_id, FinancialGoal.status == "ACTIVE")
    ).one()
    active_income_ideas = (
        db.scalar(
            select(func.count())
            .select_from(IncomeOpportunity)
            .where(
                IncomeOpportunity.user_id == user_id,
                IncomeOpportunity.stage.in_(["ACTIVE", "GENERATING"]),
            )
        )
        or 0
    )
    budget_count = (
        db.scalar(
            select(func.count())
            .select_from(CategoryBudget)
            .where(
                CategoryBudget.user_id == user_id,
                CategoryBudget.is_active.is_(True),
            )
        )
        or 0
    )
    danger_months = [
        line for line in forecast.lines if line.traffic_light in {"YELLOW", "RED"}
    ]
    first_line = forecast.lines[0] if forecast.lines else None
    monthly_margin_cents = first_line.net_cents if first_line else 0
    action_items: list[dict[str, str]] = []
    if total_debt_cents > 0:
        action_items.append(
            {
                "title": "Revisar estratégia de quitação",
                "href": "/app/prosperity#dividas",
            }
        )
    if int(goal_totals[1]) == 0:
        action_items.append(
            {"title": "Criar a primeira meta familiar", "href": "/app/prosperity#metas"}
        )
    if budget_count == 0:
        action_items.append(
            {
                "title": "Definir limites por categoria",
                "href": "/app/prosperity#orcamento",
            }
        )
    if active_income_ideas == 0:
        action_items.append(
            {
                "title": "Ativar uma oportunidade de renda",
                "href": "/app/prosperity#renda",
            }
        )
    if danger_months:
        action_items.insert(
            0,
            {
                "title": f"Proteger caixa de {danger_months[0].month.strftime('%m/%Y')}",
                "href": "/app/forecast",
            },
        )
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={
            "forecast": forecast,
            "focused_months": focused_months,
            "month_rail": month_rail,
            "selected_month": selected_month,
            "current_plan_name": active_plan.name,
            "active_page": "dashboard",
            "csrf_token": get_or_create_csrf_token(request),
            "total_debt_cents": int(total_debt_cents),
            "goal_current_cents": int(goal_totals[0]),
            "goal_target_cents": int(goal_totals[1]),
            "active_income_ideas": int(active_income_ideas),
            "danger_months": danger_months,
            "monthly_margin_cents": monthly_margin_cents,
            "action_items": action_items[:4],
        },
    )
