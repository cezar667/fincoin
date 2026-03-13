from json import JSONDecodeError

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.application.use_cases.business_control_finance import BusinessControlFinanceService
from app.infrastructure.db.session import get_db

router = APIRouter()


@router.post("/api/integrations/themembers/{webhook_path_token}/checkout-webhook")
async def themembers_checkout_webhook(
    webhook_path_token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        body = await request.json()
    except JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON invalido.") from exc

    service = BusinessControlFinanceService(db)
    signature = request.headers.get("X-Signature", "")
    source_ip = request.client.host if request.client is not None else None
    try:
        result = service.handle_checkout_webhook(
            webhook_path_token=webhook_path_token,
            signature=signature,
            body=body,
            request_id=request.state.request_id,
            source_ip=source_ip,
            user_agent=request.headers.get("User-Agent"),
            headers=dict(request.headers),
        )
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if "nao encontrado" in detail.lower() else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=status_code, detail=detail) from exc

    response_status = status.HTTP_202_ACCEPTED if result.status == "failed" else status.HTTP_200_OK
    return JSONResponse(
        status_code=response_status,
        content={
            "status": result.status,
            "detail": result.detail,
            "event_id": str(result.event.id),
            "event_status": result.event.status.value,
        },
    )
