"""
FastAPI 의존성 — 인증 및 권한 가드.

구 버전은 조회성 GET 이 전부 무인증이었다 (GET /api/users 로 전체 계정이
노출되기까지 했다). 여기서는 **인증을 기본값으로** 두고, 공개 엔드포인트만
별도 라우터로 분리한다. 라우터에 가드를 붙이는 걸 잊어도 뚫리지 않는다.

    # 보호 라우터 — 소속된 모든 라우트에 가드가 적용된다
    router = APIRouter(dependencies=[Depends(require_operator)])

    # 공개 라우터 — 가드가 필요 없는 것만 여기에 담는다
    public_router = APIRouter()

주의: FastAPI 는 라우터 레벨과 라우트 레벨 의존성을 **합친다**. 라우트에
`dependencies=[]` 를 준다고 라우터 기본값이 해제되지 않으므로, 공개
엔드포인트는 반드시 별도 라우터에 두어야 한다.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyCookie
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import decode_access_token
from app.database import get_db
from app.models.auth import Role, User

# OpenAPI 문서화 전용. 실제 값은 아래에서 직접 쿠키를 읽는다.
_cookie_scheme = APIKeyCookie(name=settings.COOKIE_NAME, auto_error=False)

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="로그인이 필요합니다.",
)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    _: str | None = Depends(_cookie_scheme),
) -> User:
    token = request.cookies.get(settings.COOKIE_NAME)
    if not token:
        raise _UNAUTHENTICATED

    payload = decode_access_token(token)
    if payload is None:
        raise _UNAUTHENTICATED

    user_id = payload.get("uid")
    if not isinstance(user_id, int):
        raise _UNAUTHENTICATED

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        # 토큰은 유효하지만 계정이 삭제·비활성화된 경우.
        raise _UNAUTHENTICATED

    return user


def require_role(minimum: Role) -> Callable[[User], User]:
    """지정 권한 이상을 요구하는 의존성을 만든다. 상위 권한은 하위를 포함한다."""

    def _guard(current_user: User = Depends(get_current_user)) -> User:
        if not Role(current_user.role).can_act_as(minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"이 작업에는 {minimum} 이상의 권한이 필요합니다.",
            )
        return current_user

    return _guard


# 자주 쓰는 가드
require_viewer = require_role(Role.VIEWER)  # = 로그인만 되어 있으면 통과
require_operator = require_role(Role.OPERATOR)
require_admin = require_role(Role.ADMIN)
