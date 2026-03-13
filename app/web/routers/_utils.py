from datetime import date
from uuid import UUID

from fastapi import HTTPException, Request, status

from app.domain.value_objects.month import Month


def parse_year_month(value: str | None, *, default: date) -> date:
    if not value:
        return Month.from_any_date(default).value
    try:
        y, m = value.split("-", maxsplit=1)
        return date(int(y), int(m), 1)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid YYYY-MM") from exc


def user_id_from_session(request: Request) -> UUID | None:
    raw = request.session.get("user_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


def plan_id_from_session(request: Request) -> UUID | None:
    raw = request.session.get("active_plan_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


def business_id_from_session(request: Request) -> UUID | None:
    raw = request.session.get("active_business_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None
