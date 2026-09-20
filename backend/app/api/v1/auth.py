from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentUser
from app.models import User
from app.schemas.auth import Token, UserCreate, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201, summary="Create an analyst account")
def register(data: UserCreate, db: Session = DB):
    return auth_service.register_user(db, data)


@router.post("/login", response_model=Token, summary="Obtain a JWT (OAuth2 password flow)")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = DB):
    user, token = auth_service.authenticate(db, form.username, form.password)
    return Token(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut, summary="Current user profile")
def me(user: User = CurrentUser):
    return user
