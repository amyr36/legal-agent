from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.database import get_db
from app.models.identity.user import User
from app.schemas.system.auth_shema import (
    OTPRequest,
    OTPVerify,
    RegisterUser,
    Token,
)
from app.services.system.sms_service import sms_service

import secrets
from datetime import datetime, timedelta, timezone


router = APIRouter(
    prefix="/auth",
    tags=["Auth"],
)


DEFAULT_ROLE_ID = 1

_otp_store: dict[str, tuple[str, datetime]] = {}
_verified_phones: set[str] = set()


def _generate_otp() -> str:
    return "".join(
        str(secrets.randbelow(10))
        for _ in range(6)
    )


@router.post("/request-otp")
def request_otp(
    payload: OTPRequest,
):
    """
    Generate and send an OTP.
    """

    code = _generate_otp()

    expires_at = (
        datetime.now(timezone.utc)
        + timedelta(minutes=5)
    )

    _otp_store[payload.phone_number] = (
        code,
        expires_at,
    )

    success = sms_service.send_otp(
        payload.phone_number,
        code,
    )

    if not success:
        _otp_store.pop(
            payload.phone_number,
            None,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send OTP.",
        )

    return {
        "message": "OTP sent successfully."
    }


@router.post("/verify-otp")
def verify_otp(
    payload: OTPVerify,
    db: Session = Depends(get_db),
):
    """
    Verify OTP.

    Existing user:
        OTP → JWT

    New user:
        OTP → phone verification → registration
    """

    stored = _otp_store.get(
        payload.phone_number
    )

    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No OTP requested.",
        )

    code, expires_at = stored

    if datetime.now(timezone.utc) > expires_at:
        _otp_store.pop(
            payload.phone_number,
            None,
        )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP has expired.",
        )

    if not secrets.compare_digest(
        code,
        payload.code,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OTP.",
        )

    # OTP can only be used once
    _otp_store.pop(
        payload.phone_number,
        None,
    )

    user = db.scalar(
        select(User).where(
            User.phone_number
            == payload.phone_number
        )
    )

    # Existing user → login
    if user is not None:

        token = create_access_token(
            subject=user.user_id
        )

        return Token(
            access_token=token
        )

    # New user → phone verified
    _verified_phones.add(
        payload.phone_number
    )

    return {
        "registered": False,
        "phone_verified": True,
        "message": (
            "Phone verified. "
            "Please complete registration."
        ),
    }


@router.post(
    "/register",
    response_model=Token,
)
def register_user(
    payload: RegisterUser,
    db: Session = Depends(get_db),
):
    """
    Register a new user after phone verification.
    """

    # Check whether phone was verified
    if payload.phone_number not in _verified_phones:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number has not been verified.",
        )

    # Check phone uniqueness
    existing_user = db.scalar(
        select(User).where(
            User.phone_number
            == payload.phone_number
        )
    )

    if existing_user is not None:
        _verified_phones.discard(
            payload.phone_number
        )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already exists.",
        )

    # Check username uniqueness
    username_exists = db.scalar(
        select(User).where(
            User.username
            == payload.username
        )
    )

    if username_exists is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists.",
        )

    # Create user
    user = User(
        username=payload.username,
        phone_number=payload.phone_number,
        role_id=DEFAULT_ROLE_ID,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    # Phone verification has been consumed
    _verified_phones.remove(
        payload.phone_number
    )

    # Login immediately after registration
    token = create_access_token(
        subject=user.user_id
    )

    return Token(
        access_token=token
    )