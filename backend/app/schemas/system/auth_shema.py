from __future__ import annotations

from pydantic import BaseModel, field_validator


class UserRegister(BaseModel):
    username: str
    phone_number: str
    password: str
    role_id: int

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"