from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.infrastructure.db.base import Base
from app.infrastructure.db.legacy import ensure_sqlite_legacy_business_control_schema
from app.infrastructure.db.session import engine
from app.infrastructure.settings.config import get_settings
from app.web.routers import auth, business_control, dashboard, forecast, imports, plans, themembers, transactions

from app.infrastructure.db import models as _models  # noqa: F401


def brl(cents: int) -> str:
    amount = Decimal(cents) / Decimal("100")
    text = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {text}"


def problem(
    *,
    request: Request,
    status_code: int,
    title: str,
    detail: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "type": "about:blank",
            "title": title,
            "detail": detail,
            "instance": str(request.url.path),
        },
    )


def _ensure_dev_legacy_columns() -> None:
    inspector = inspect(engine)
    try:
        account_columns = {item["name"] for item in inspector.get_columns("accounts")}
    except Exception:
        ensure_sqlite_legacy_business_control_schema(engine)
        return
    if "initial_balance_cents" not in account_columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE accounts "
                    "ADD COLUMN initial_balance_cents BIGINT NOT NULL DEFAULT 0"
                )
            )
    ensure_sqlite_legacy_business_control_schema(engine)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="FinSight", version="0.1.0")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        same_site="lax",
        https_only=settings.session_cookie_secure,
        session_cookie="finsight_session",
    )
    app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

    templates = Jinja2Templates(directory="app/web/templates")
    templates.env.filters["brl"] = brl
    app.state.templates = templates

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id", str(uuid4()))
        request.state.request_id = request_id
        css_path = Path("app/web/static/css/app.css")
        try:
            request.state.css_version = str(int(css_path.stat().st_mtime))
        except OSError:
            request.state.css_version = "1"
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if request.url.path.startswith("/api"):
            detail = exc.detail if isinstance(exc.detail, str) else "Request error"
            return problem(request=request, status_code=exc.status_code, title="Request error", detail=detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, _: RequestValidationError):
        if request.url.path.startswith("/api"):
            return problem(
                request=request,
                status_code=422,
                title="Validation error",
                detail="Payload validation failed",
            )
        return JSONResponse(status_code=422, content={"detail": "Validation error"})

    @app.on_event("startup")
    def startup() -> None:
        if settings.app_env == "development":
            Base.metadata.create_all(bind=engine)
            _ensure_dev_legacy_columns()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "time": datetime.now(tz=timezone.utc).isoformat()}

    app.include_router(auth.router)
    app.include_router(plans.router)
    app.include_router(dashboard.router)
    app.include_router(business_control.router)
    app.include_router(themembers.router)
    app.include_router(transactions.router)
    app.include_router(forecast.router)
    app.include_router(imports.router)
    return app


app = create_app()
