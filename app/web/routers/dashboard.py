from datetime import date

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.application.use_cases.build_forecast import BuildForecastUseCase
from app.infrastructure.auth.csrf import get_or_create_csrf_token
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
    forecast = BuildForecastUseCase(SQLAlchemyForecastRepository(db)).execute(
        user_id=user_id,
        from_month=selected_month,
        months=6,
        plan_id=active_plan.id,
    )
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
