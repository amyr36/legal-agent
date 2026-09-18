from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.db.database import get_db
from app.models.identity.user import User
from app.schemas.system.auth_shema import Token, UserLogin, UserRegister


router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    """Register a new user and return a JWT token."""
    existing = db.scalar(
        select(User).where(User.phone_number == payload.phone_number)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This phone number is already registered",
        )

    user = User(
        username=payload.username,
        phone_number=payload.phone_number,
        hashed_password=hash_password(payload.password),
        role_id=payload.role_id

    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(subject=user.user_id)
    return Token(access_token=token)


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    """Authenticate a user and return a JWT token."""
    user = db.scalar(
        select(User).where(User.username == payload.username)
    )

    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect phone number or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(subject=user.user_id)
    return Token(access_token=token)


@router.post("/token", response_model=Token)
def login_oauth2(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    ):
    """OAuth2-compatible login endpoint for Swagger UI.

    Swagger sends `username` + `password` as form data.
    """
    user = db.scalar(
        select(User).where(User.username == form_data.username)
    )

    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(subject=user.user_id)
    return Token(access_token=token)