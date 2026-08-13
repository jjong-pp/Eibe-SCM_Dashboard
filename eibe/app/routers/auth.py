"""인증 엔드포인트 — 로그인 / 로그아웃 / 현재 사용자."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import get_current_user
from app.core.security import (
    create_access_token,
    generate_csrf_token,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models.auth import User
from app.schemas.auth import LoginRequest, LoginResponse, UserResponse
from app.schemas.common import MessageResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["인증"])

# 존재하지 않는 사용자에게도 동일한 해싱 비용을 치르게 해서,
# 응답 시간 차이로 계정 존재 여부를 알아내지 못하게 한다.
_DUMMY_HASH = hash_password("dummy-password-for-timing-equalization")


def _set_auth_cookies(response: Response, token: str, csrf_token: str) -> None:
    common = {
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "max_age": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "path": "/",
    }
    # 세션 토큰 — JS 가 읽을 수 없다. XSS 로 탈취되지 않는다.
    response.set_cookie(settings.COOKIE_NAME, token, httponly=True, **common)
    # CSRF 토큰 — 이중 제출 방식이므로 JS 가 읽어서 헤더에 실어야 한다.
    response.set_cookie(
        settings.CSRF_COOKIE_NAME, csrf_token, httponly=False, **common
    )


def _clear_auth_cookies(response: Response) -> None:
    for name in (settings.COOKIE_NAME, settings.CSRF_COOKIE_NAME):
        response.delete_cookie(
            name,
            path="/",
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
        )


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """로그인. 성공 시 세션·CSRF 쿠키를 설정한다."""
    user = db.query(User).filter(User.username == payload.username).first()

    password_ok = (
        verify_password(payload.password, user.password_hash)
        if user
        else verify_password(payload.password, _DUMMY_HASH)
    )

    if not user or not password_ok or not user.is_active:
        # 사유를 구분해 알려주지 않는다 (계정 열거 방지).
        logger.warning("로그인 실패: username=%s", payload.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )

    token = create_access_token(
        subject=user.username, role=str(user.role), user_id=user.id
    )
    csrf_token = generate_csrf_token()
    _set_auth_cookies(response, token, csrf_token)

    logger.info("로그인 성공: username=%s role=%s", user.username, user.role)
    return LoginResponse(
        user=UserResponse.model_validate(user), csrf_token=csrf_token
    )


@router.post("/logout", response_model=MessageResponse)
def logout(response: Response) -> MessageResponse:
    _clear_auth_cookies(response)
    return MessageResponse(message="로그아웃되었습니다.")


@router.get("/me", response_model=UserResponse)
def read_current_user(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    return UserResponse.model_validate(current_user)
