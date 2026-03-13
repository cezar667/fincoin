import secrets

from fastapi import HTTPException, Request, status

CSRF_KEY = "csrf_token"


def get_or_create_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_KEY)
    if token:
        return str(token)
    token = secrets.token_urlsafe(32)
    request.session[CSRF_KEY] = token
    return token


def validate_csrf(request: Request, token: str | None) -> None:
    expected = request.session.get(CSRF_KEY)
    if not token or not expected or not secrets.compare_digest(str(token), str(expected)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token")

