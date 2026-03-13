from datetime import date

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.use_cases.build_forecast import BuildForecastUseCase
from app.infrastructure.auth.csrf import get_or_create_csrf_token
from app.infrastructure.db.models.financial_plan import FinancialPlan
from app.infrastructure.db.session import get_db
from app.infrastructure.repositories.transaction_repo import SQLAlchemyForecastRepository
from app.web.routers._utils import parse_year_month, plan_id_from_session, user_id_from_session

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
        },
    )
