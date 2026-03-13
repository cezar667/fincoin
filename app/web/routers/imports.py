from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.dto.import_dto import (
    ApplyImportPayloadDTO,
    CSVColumnMappingDTO,
    ExternalTransactionReadDTO,
)
from app.application.use_cases.apply_import_to_transactions import ApplyImportToTransactionsUseCase
from app.application.use_cases.import_csv_to_staging import ImportCSVToStagingUseCase
from app.infrastructure.auth.csrf import get_or_create_csrf_token, validate_csrf
from app.infrastructure.auth.session import get_current_user_id
from app.infrastructure.db.models.account import Account
from app.infrastructure.db.models.category import Category
from app.infrastructure.db.models.credit_card import CreditCard
from app.infrastructure.db.models.enums import ExternalTransactionReviewStatus
from app.infrastructure.db.models.financial_plan import FinancialPlan
from app.infrastructure.db.session import get_db
from app.infrastructure.importers.credit_card_csv_importer import CreditCardCSVImporter
from app.infrastructure.repositories.external_tx_repo import SQLAlchemyExternalTransactionRepository
from app.infrastructure.repositories.import_file_repo import SQLAlchemyImportFileRepository
from app.web.routers._utils import plan_id_from_session, user_id_from_session

router = APIRouter()
MAX_IMPORT_FILE_SIZE_BYTES = 5 * 1024 * 1024


def _resolve_user_and_plan(request: Request, db: Session) -> tuple[UUID, FinancialPlan] | RedirectResponse:
    user_id = user_id_from_session(request)
    if user_id is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    plan_id = plan_id_from_session(request)
    if plan_id is None:
        return RedirectResponse("/app/plans", status_code=status.HTTP_303_SEE_OTHER)
    plan = db.scalar(select(FinancialPlan).where(FinancialPlan.id == plan_id, FinancialPlan.user_id == user_id))
    if plan is None:
        request.session.pop("active_plan_id", None)
        return RedirectResponse("/app/plans", status_code=status.HTTP_303_SEE_OTHER)
    return user_id, plan


def _parse_note_counts(note: str | None) -> dict[str, int]:
    counts = {"total": 0, "importadas": 0, "duplicadas": 0, "erros": 0}
    if not note:
        return counts
    for part in note.split(";"):
        if "=" not in part:
            continue
        key, raw_value = part.split("=", maxsplit=1)
        key = key.strip().lower()
        value = raw_value.strip()
        if key in counts and value.isdigit():
            counts[key] = int(value)
    return counts


def _validate_upload_size(upload: UploadFile) -> None:
    upload.file.seek(0, 2)
    size = upload.file.tell()
    upload.file.seek(0)
    if size > MAX_IMPORT_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Arquivo maior que o limite de 5MB.",
        )


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "on", "yes", "sim"}


async def _build_apply_payload_from_request(request: Request) -> ApplyImportPayloadDTO:
    content_type = (request.headers.get("content-type") or "").lower()
    if content_type.startswith("application/json"):
        data = await request.json()
        return ApplyImportPayloadDTO.model_validate(data)
    form = await request.form()
    raw_approved_ids = [item for item in form.getlist("approved_ids") if item]
    csv_approved_ids = str(form.get("approved_ids_csv") or "").strip()
    if csv_approved_ids:
        raw_approved_ids.extend([item.strip() for item in csv_approved_ids.split(",") if item.strip()])
    payload_data = {
        "default_account_id": form.get("default_account_id"),
        "default_category_id": form.get("default_category_id") or None,
        "approve_all": _parse_bool(str(form.get("approve_all") or "0")),
        "approved_ids": raw_approved_ids,
    }
    return ApplyImportPayloadDTO.model_validate(payload_data)


@router.get("/app/import")
def import_page(request: Request, db: Session = Depends(get_db)):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx
    cards = list(db.scalars(select(CreditCard).where(CreditCard.user_id == user_id).order_by(CreditCard.name.asc())))
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="imports/upload.html",
        context={
            "active_page": "transactions",
            "transactions_subpage": "import",
            "current_plan_name": plan.name,
            "csrf_token": get_or_create_csrf_token(request),
            "cards": cards,
            "max_file_size_mb": 5,
        },
    )


@router.post("/api/import/csv")
def import_csv(
    request: Request,
    file: UploadFile = File(...),
    credit_card_id: UUID | None = Form(default=None),
    csrf_token: str = Form(...),
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    validate_csrf(request, csrf_token)
    _validate_upload_size(file)

    if credit_card_id is not None:
        card = db.get(CreditCard, credit_card_id)
        if card is None or card.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Cartao invalido")

    use_case = ImportCSVToStagingUseCase(
        importer=CreditCardCSVImporter(),
        import_file_repo=SQLAlchemyImportFileRepository(db),
        external_tx_repo=SQLAlchemyExternalTransactionRepository(db),
    )
    try:
        summary = use_case.execute(
            user_id=user_id,
            filename=file.filename or "import.csv",
            stream=file.file,
            card_id=credit_card_id,
            mapping=CSVColumnMappingDTO(),
        )
        return summary.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    finally:
        file.file.close()


@router.get("/app/import/{import_file_id}/review")
def review_import_page(import_file_id: UUID, request: Request, db: Session = Depends(get_db)):
    session_ctx = _resolve_user_and_plan(request, db)
    if isinstance(session_ctx, RedirectResponse):
        return session_ctx
    user_id, plan = session_ctx

    import_file_repo = SQLAlchemyImportFileRepository(db)
    external_repo = SQLAlchemyExternalTransactionRepository(db)
    import_file = import_file_repo.get_for_user(import_file_id=import_file_id, user_id=user_id)
    if import_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Importacao nao encontrada")

    items = external_repo.list_by_import_file(
        user_id=user_id,
        import_file_id=import_file_id,
        status=ExternalTransactionReviewStatus.PENDING,
    )
    summary_counts = _parse_note_counts(import_file.note)
    review_counts = external_repo.count_by_review_status(user_id=user_id, import_file_id=import_file_id)
    accounts = list(db.scalars(select(Account).where(Account.user_id == user_id).order_by(Account.name.asc())))
    categories = list(db.scalars(select(Category).where(Category.user_id == user_id).order_by(Category.name.asc())))
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="imports/review.html",
        context={
            "active_page": "transactions",
            "transactions_subpage": "import",
            "current_plan_name": plan.name,
            "csrf_token": get_or_create_csrf_token(request),
            "import_file": import_file,
            "items": items,
            "accounts": accounts,
            "categories": categories,
            "count_pending": review_counts.get(ExternalTransactionReviewStatus.PENDING.value, 0),
            "count_duplicates": summary_counts["duplicadas"],
            "count_errors": summary_counts["erros"],
        },
    )


@router.get("/api/import/{import_file_id}/items")
def list_import_items(
    import_file_id: UUID,
    status_value: str | None = Query(default="PENDING", alias="status"),
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    import_file_repo = SQLAlchemyImportFileRepository(db)
    external_repo = SQLAlchemyExternalTransactionRepository(db)
    import_file = import_file_repo.get_for_user(import_file_id=import_file_id, user_id=user_id)
    if import_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Importacao nao encontrada")

    review_status = None
    if status_value:
        try:
            review_status = ExternalTransactionReviewStatus(status_value.upper())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Status invalido") from exc

    rows = external_repo.list_by_import_file(user_id=user_id, import_file_id=import_file_id, status=review_status)
    return [ExternalTransactionReadDTO.model_validate(item).model_dump(mode="json") for item in rows]


@router.post("/api/import/{import_file_id}/apply")
async def apply_import(
    import_file_id: UUID,
    request: Request,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    content_type = (request.headers.get("content-type") or "").lower()
    token: str | None
    if content_type.startswith("application/json"):
        token = request.headers.get("X-CSRF-Token")
    else:
        form = await request.form()
        token = str(form.get("csrf_token") or "")
    validate_csrf(request, token)

    payload = await _build_apply_payload_from_request(request)
    active_plan_id = plan_id_from_session(request)
    use_case = ApplyImportToTransactionsUseCase(
        db=db,
        import_file_repo=SQLAlchemyImportFileRepository(db),
        external_tx_repo=SQLAlchemyExternalTransactionRepository(db),
    )
    try:
        result = use_case.execute(
            user_id=user_id,
            import_file_id=import_file_id,
            payload=payload,
            active_plan_id=active_plan_id,
        )
        return result.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/api/import/items/{external_tx_id}/set-mapping")
async def set_import_item_mapping(
    external_tx_id: UUID,
    request: Request,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    form = await request.form()
    token = str(form.get("csrf_token") or request.headers.get("X-CSRF-Token") or "")
    validate_csrf(request, token)

    category_id_raw = str(form.get("category_id") or "").strip()
    account_id_raw = str(form.get("account_id") or "").strip()
    try:
        category_id = UUID(category_id_raw) if category_id_raw else None
        account_id = UUID(account_id_raw) if account_id_raw else None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="UUID invalido") from exc

    external_repo = SQLAlchemyExternalTransactionRepository(db)
    row = external_repo.get_for_user(external_tx_id=external_tx_id, user_id=user_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Linha nao encontrada")

    if category_id is not None:
        category = db.get(Category, category_id)
        if category is None or category.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Categoria invalida")
    if account_id is not None:
        account = db.get(Account, account_id)
        if account is None or account.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Conta invalida")

    updated = external_repo.set_mapping(external_tx=row, category_id=category_id, account_id=account_id)
    return ExternalTransactionReadDTO.model_validate(updated).model_dump(mode="json")


@router.post("/api/import/items/{external_tx_id}/reject")
async def reject_import_item(
    external_tx_id: UUID,
    request: Request,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    form = await request.form()
    token = str(form.get("csrf_token") or request.headers.get("X-CSRF-Token") or "")
    validate_csrf(request, token)

    external_repo = SQLAlchemyExternalTransactionRepository(db)
    row = external_repo.get_for_user(external_tx_id=external_tx_id, user_id=user_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Linha nao encontrada")
    external_repo.reject(external_tx=row)

    if request.headers.get("HX-Request") == "true":
        return HTMLResponse("")
    return {"status": "ok"}
