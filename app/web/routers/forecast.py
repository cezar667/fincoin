from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.dto.forecast_dto import ForecastDTO
from app.application.use_cases.build_forecast import BuildForecastUseCase
from app.infrastructure.auth.csrf import get_or_create_csrf_token
from app.infrastructure.auth.session import get_current_user_id
from app.infrastructure.db.models.financial_plan import FinancialPlan
from app.infrastructure.db.session import get_db
from app.infrastructure.repositories.transaction_repo import SQLAlchemyForecastRepository
from app.web.routers._utils import parse_year_month, plan_id_from_session, user_id_from_session

router = APIRouter()

TRAFFIC_LIGHT_LABELS = {
    "GREEN": "Verde",
    "YELLOW": "Amarelo",
    "RED": "Vermelho",
}
HORIZON_OPTIONS = (12, 24)


def _is_valid_horizon(months: int) -> bool:
    return months in HORIZON_OPTIONS


def _coerce_horizon(months: int) -> int:
    if _is_valid_horizon(months):
        return months
    return HORIZON_OPTIONS[0]


@router.get("/app/forecast")
def forecast_page(
    request: Request,
    from_month: str | None = Query(default=None, alias="from"),
    months: int = Query(default=12, ge=1, le=24),
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
    selected = parse_year_month(from_month, default=date.today())
    selected_horizon = _coerce_horizon(months)
    forecast = BuildForecastUseCase(SQLAlchemyForecastRepository(db)).execute(
        user_id=user_id,
        from_month=selected,
        months=selected_horizon,
        plan_id=active_plan.id,
    )
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="forecast/index.html",
        context={
            "forecast": forecast,
            "traffic_light_labels": TRAFFIC_LIGHT_LABELS,
            "selected_from_month": selected,
            "selected_horizon": selected_horizon,
            "horizon_options": HORIZON_OPTIONS,
            "current_plan_name": active_plan.name,
            "active_page": "forecast",
            "csrf_token": get_or_create_csrf_token(request),
        },
    )


@router.get("/api/forecast", response_model=ForecastDTO)
def forecast_api(
    from_month: str | None = Query(default=None, alias="from"),
    months: int = Query(default=12, ge=1, le=24),
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    selected = parse_year_month(from_month, default=date.today())
    if not _is_valid_horizon(months):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Horizonte invalido. Use 12 ou 24 meses.")
    selected_horizon = months
    return BuildForecastUseCase(SQLAlchemyForecastRepository(db)).execute(
        user_id=user_id,
        from_month=selected,
        months=selected_horizon,
    )
