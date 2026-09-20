from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB, AdminOnly
from app.audit import events, record
from app.models import User, UserRole
from app.schemas.auth import UserCreate, UserOut
from app.services import auth_service

router = APIRouter(prefix="/users", tags=["users"])


class UserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None


class AdminUserCreate(UserCreate):
    role: UserRole = UserRole.analyst


@router.get("", response_model=list[UserOut], summary="All users (admin)")
def list_users(user: User = AdminOnly, db: Session = DB):
    return db.execute(select(User).order_by(User.id)).scalars().all()


@router.post("", response_model=UserOut, status_code=201, summary="Create a user with a role (admin)")
def create_user(data: AdminUserCreate, user: User = AdminOnly, db: Session = DB):
    return auth_service.register_user(db, data, role=data.role)


@router.patch("/{user_id}", response_model=UserOut, summary="Change role or active state (admin)")
def update_user(user_id: int, data: UserUpdate, admin: User = AdminOnly, db: Session = DB):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "User not found.")
    if target.id == admin.id and (data.role not in (None, UserRole.admin) or data.is_active is False):
        raise HTTPException(409, "You cannot demote or deactivate your own account.")
    before = {"role": target.role.value, "is_active": target.is_active}
    if data.role is not None:
        target.role = data.role
    if data.is_active is not None:
        target.is_active = data.is_active
    record(db, event_type="user.updated", target_type="user", target_id=target.id, actor_id=admin.id,
           payload={"before": before, "after": {"role": target.role.value, "is_active": target.is_active}})
    db.commit()
    return target
