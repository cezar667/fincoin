from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.auth.csrf import get_or_create_csrf_token, validate_csrf
from app.infrastructure.auth.password import verify_password
from app.infrastructure.db.models.user import User
from app.infrastructure.db.session import get_db

router = APIRouter()


@router.get("/login")
def login_page(request: Request):
    t = request.app.state.templates
    return t.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={"csrf_token": get_or_create_csrf_token(request)},
    )


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    validate_csrf(request, csrf_token)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        t = request.app.state.templates
        return t.TemplateResponse(
            request=request,
            name="auth/login.html",
            status_code=status.HTTP_401_UNAUTHORIZED,
            context={"csrf_token": get_or_create_csrf_token(request), "error": "Credenciais invalidas"},
        )

    request.session.clear()
    request.session["user_id"] = str(user.id)
    request.session["csrf_token"] = get_or_create_csrf_token(request)
    return RedirectResponse("/app/plans", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    validate_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
