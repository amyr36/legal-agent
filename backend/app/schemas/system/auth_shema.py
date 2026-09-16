from pydantic import BaseModel


class OTPRequest(BaseModel):
    phone_number: str


class OTPVerify(BaseModel):
    phone_number: str
    code: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterUser(BaseModel):
    phone_number: str
    username: str