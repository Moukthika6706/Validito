from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import events, record
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User, UserRole
from app.schemas.auth import UserCreate


def register_user(db: Session, data: UserCreate, *, role: UserRole = UserRole.analyst) -> User:
    existing = db.execute(select(User).where(User.email == data.email.lower())).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email already exists.")
    user = User(
        email=data.email.lower(),
        password_hash=hash_password(data.password),
        full_name=data.full_name.strip(),
        role=role,
    )
    db.add(user)
    db.flush()
    record(db, event_type=events.USER_REGISTERED, target_type="user", target_id=user.id, actor_id=user.id, payload={"email": user.email, "role": role.value})
    db.commit()
    return user


def authenticate(db: Session, email: str, password: str) -> tuple[User, str]:
    user = db.execute(select(User).where(User.email == email.lower())).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.", headers={"WWW-Authenticate": "Bearer"}
        )
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled.")
    token = create_access_token(subject=str(user.id), role=user.role.value)
    record(db, event_type=events.USER_LOGIN, target_type="user", target_id=user.id, actor_id=user.id)
    db.commit()
    return user, token
