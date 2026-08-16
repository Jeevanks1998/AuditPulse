"""
schemas/user.py

Request/response models for authentication and the current-user identity
(api/auth.py). `UserOut` is also reused as the embedded `user` field on
`TokenOut` and as the base of `SettingsOut` (api/settings.py) wherever a
lightweight, public-safe view of a User row is needed — never expose
`hashed_password` or `api_key` through it.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegister(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    company: Optional[str] = ""


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserEmailLogin(BaseModel):
    """Internal, passwordless login — email only. See api/auth.py's
    `/auth/login-email` route: finds-or-creates the user by email and
    signs them straight in, no password required."""

    email: EmailStr
    name: Optional[str] = None


class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    company: str
    ai_provider: str

    model_config = ConfigDict(from_attributes=True)


class TokenOut(BaseModel):
    token: str
    token_type: str = "bearer"
    user: UserOut
