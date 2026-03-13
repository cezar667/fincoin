from uuid import UUID

from fastapi import HTTPException, Request, status


def get_current_user_id(request: Request) -> UUID:
    raw = request.session.get("user_id")
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return UUID(str(raw))

