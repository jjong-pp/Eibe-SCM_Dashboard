"""인증 관련 요청/응답 스키마."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.models.auth import Role
from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    # 상한을 두는 이유: bcrypt 로 넘기기 전 과도한 입력을 차단한다.
    password: str = Field(min_length=1, max_length=256)


class UserResponse(ORMModel):
    id: int
    username: str
    name: str
    email: str | None
    role: Role
    is_active: bool


class LoginResponse(BaseModel):
    """토큰은 httpOnly 쿠키로만 전달한다. 본문에 담지 않는다."""

    user: UserResponse
    csrf_token: str


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=10, max_length=256)
    name: str = Field(min_length=1, max_length=64)
    email: EmailStr | None = None
    role: Role = Role.VIEWER


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    email: EmailStr | None = None
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=256)
