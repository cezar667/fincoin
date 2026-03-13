from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.infrastructure.auth.csrf import get_or_create_csrf_token, validate_csrf
from app.infrastructure.db.models.financial_plan import FinancialPlan
from app.infrastructure.db.models.installment import Installment
from app.infrastructure.db.models.plan_installment import PlanInstallment
from app.infrastructure.db.models.plan_recurring_rule import PlanRecurringRule
from app.infrastructure.db.models.plan_transaction import PlanTransaction
from app.infrastructure.db.models.recurring_rule import RecurringRule
from app.infrastructure.db.models.transaction import Transaction
from app.infrastructure.db.session import get_db
from app.web.routers._utils import plan_id_from_session, user_id_from_session

router = APIRouter()


def _set_flash(request: Request, *, kind: str, message: str) -> None:
    request.session["flash_message"] = {"kind": kind, "message": message}


def _get_user_plan_or_none(db: Session, *, user_id: UUID, plan_id: UUID) -> FinancialPlan | None:
    return db.scalar(
        select(FinancialPlan).where(
            FinancialPlan.id == plan_id,
            FinancialPlan.user_id == user_id,
        )
    )


@router.get("/app/plans")
def plans_page(request: Request, db: Session = Depends(get_db)):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    plans = list(
        db.scalars(
            select(FinancialPlan)
            .where(FinancialPlan.user_id == user_id)
            .order_by(FinancialPlan.created_at.desc())
        )
    )
    active_plan_id = plan_id_from_session(request)
    active_plan: FinancialPlan | None = None
    if active_plan_id is not None:
        active_plan = next((item for item in plans if item.id == active_plan_id), None)
        if active_plan is None:
            request.session.pop("active_plan_id", None)

    flash = request.session.pop("flash_message", None)
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="plans/index.html",
        context={
            "plans": plans,
            "active_plan_id": active_plan.id if active_plan else None,
            "current_plan_name": active_plan.name if active_plan else None,
            "active_page": "plans",
            "csrf_token": get_or_create_csrf_token(request),
            "flash": flash,
        },
    )


@router.post("/app/plans")
def create_plan_form(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    validate_csrf(request, csrf_token)

    try:
        existing_plan_count = db.scalar(
            select(func.count()).select_from(FinancialPlan).where(FinancialPlan.user_id == user_id)
        )
        plan_name = name.strip()
        if not plan_name:
            raise ValueError("Nome do planejamento e obrigatorio.")
        plan = FinancialPlan(
            user_id=user_id,
            name=plan_name,
            description=description.strip() or None,
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)

        if existing_plan_count == 0:
            transaction_ids = list(db.scalars(select(Transaction.id).where(Transaction.user_id == user_id)))
            recurring_rule_ids = list(
                db.scalars(select(RecurringRule.id).where(RecurringRule.user_id == user_id))
            )
            installment_ids = list(
                db.scalars(select(Installment.id).where(Installment.user_id == user_id))
            )
            for transaction_id in transaction_ids:
                db.add(PlanTransaction(plan_id=plan.id, transaction_id=transaction_id))
            for recurring_rule_id in recurring_rule_ids:
                db.add(PlanRecurringRule(plan_id=plan.id, recurring_rule_id=recurring_rule_id))
            for installment_id in installment_ids:
                db.add(PlanInstallment(plan_id=plan.id, installment_id=installment_id))
            db.commit()

        request.session["active_plan_id"] = str(plan.id)
        _set_flash(request, kind="ok", message="Planejamento criado e selecionado.")
        return RedirectResponse("/app/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao criar planejamento: {exc}")
        return RedirectResponse("/app/plans", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/plans/{plan_id}/activate")
def activate_plan(
    plan_id: UUID,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    validate_csrf(request, csrf_token)

    plan = _get_user_plan_or_none(db, user_id=user_id, plan_id=plan_id)
    if plan is None:
        _set_flash(request, kind="error", message="Planejamento nao encontrado.")
        return RedirectResponse("/app/plans", status_code=status.HTTP_303_SEE_OTHER)

    request.session["active_plan_id"] = str(plan.id)
    _set_flash(request, kind="ok", message=f"Planejamento '{plan.name}' selecionado.")
    return RedirectResponse("/app/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/plans/{plan_id}/update")
def update_plan(
    plan_id: UUID,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    validate_csrf(request, csrf_token)

    plan = _get_user_plan_or_none(db, user_id=user_id, plan_id=plan_id)
    if plan is None:
        _set_flash(request, kind="error", message="Planejamento nao encontrado.")
        return RedirectResponse("/app/plans", status_code=status.HTTP_303_SEE_OTHER)

    try:
        plan_name = name.strip()
        if not plan_name:
            raise ValueError("Nome do planejamento e obrigatorio.")
        plan.name = plan_name
        plan.description = description.strip() or None
        db.add(plan)
        db.commit()
        _set_flash(request, kind="ok", message="Planejamento atualizado.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao atualizar planejamento: {exc}")
    return RedirectResponse("/app/plans", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/app/plans/{plan_id}/delete")
def delete_plan(
    plan_id: UUID,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    validate_csrf(request, csrf_token)

    plan = _get_user_plan_or_none(db, user_id=user_id, plan_id=plan_id)
    if plan is None:
        _set_flash(request, kind="error", message="Planejamento nao encontrado.")
        return RedirectResponse("/app/plans", status_code=status.HTTP_303_SEE_OTHER)

    try:
        transaction_ids = list(
            db.scalars(
                select(PlanTransaction.transaction_id).where(PlanTransaction.plan_id == plan.id)
            )
        )
        recurring_rule_ids = list(
            db.scalars(
                select(PlanRecurringRule.recurring_rule_id).where(PlanRecurringRule.plan_id == plan.id)
            )
        )
        installment_ids = list(
            db.scalars(
                select(PlanInstallment.installment_id).where(PlanInstallment.plan_id == plan.id)
            )
        )

        db.execute(delete(PlanTransaction).where(PlanTransaction.plan_id == plan.id))
        db.execute(delete(PlanRecurringRule).where(PlanRecurringRule.plan_id == plan.id))
        db.execute(delete(PlanInstallment).where(PlanInstallment.plan_id == plan.id))

        if transaction_ids:
            db.execute(
                delete(Transaction).where(
                    Transaction.user_id == user_id,
                    Transaction.id.in_(transaction_ids),
                )
            )
        if recurring_rule_ids:
            db.execute(
                delete(RecurringRule).where(
                    RecurringRule.user_id == user_id,
                    RecurringRule.id.in_(recurring_rule_ids),
                )
            )
        if installment_ids:
            db.execute(
                delete(Installment).where(
                    Installment.user_id == user_id,
                    Installment.id.in_(installment_ids),
                )
            )

        db.delete(plan)
        db.commit()

        active_plan_id = plan_id_from_session(request)
        if active_plan_id == plan_id:
            request.session.pop("active_plan_id", None)
        _set_flash(request, kind="ok", message="Planejamento removido.")
    except Exception as exc:
        db.rollback()
        _set_flash(request, kind="error", message=f"Falha ao remover planejamento: {exc}")
    return RedirectResponse("/app/plans", status_code=status.HTTP_303_SEE_OTHER)
