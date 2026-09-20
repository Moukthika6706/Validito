"""FastAPI dependencies: DB session, current user, role guards."""

from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_token
from app.models import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

DB = Depends(get_db)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = DB) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise credentials_error
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_error
    return user


CurrentUser = Depends(get_current_user)


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    def guard(user: User = CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(r.value for r in roles)}",
            )
        return user

    return guard


ReviewerOrAdmin = Depends(require_roles(UserRole.reviewer, UserRole.admin))
AdminOnly = Depends(require_roles(UserRole.admin))


def can_access_document(user: User, owner_id: int) -> bool:
    """Analysts see their own uploads; reviewers and admins see everything."""
    return user.role in (UserRole.reviewer, UserRole.admin) or user.id == owner_id
