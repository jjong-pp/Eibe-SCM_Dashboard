"""
요청 미들웨어 — 요청 ID 부여, CSRF 검증.

CSRF 를 의존성이 아닌 미들웨어로 둔 이유: 라우트마다 붙이는 방식은
언젠가 빠뜨린다. 상태를 바꾸는 모든 요청에 예외 없이 적용되어야 한다.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.core.logging import request_id_var
from app.core.security import csrf_tokens_match

logger = logging.getLogger(__name__)

# 본문을 변경하지 않는 메서드는 CSRF 검증 대상이 아니다.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# 세션 쿠키가 아직 없는 상태에서 호출되는 경로.
CSRF_EXEMPT_PATHS = frozenset({"/api/auth/login", "/api/auth/logout"})

RequestHandler = Callable[[Request], Awaitable[Response]]


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


class CsrfMiddleware(BaseHTTPMiddleware):
    """이중 제출 쿠키(double-submit cookie) 방식.

    세션 쿠키가 httpOnly 라 JS 가 읽을 수 없으므로, 별도의 CSRF 쿠키를
    JS 가 읽어 헤더로 되돌려보낸다. 다른 출처의 사이트는 쿠키를 읽을 수
    없으므로 헤더를 맞출 수 없다.
    """

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        if request.method in SAFE_METHODS or request.url.path in CSRF_EXEMPT_PATHS:
            return await call_next(request)

        # 세션이 없으면 CSRF 공격 대상 자체가 아니다. 인증 단계에서 401 이 난다.
        if not request.cookies.get(settings.COOKIE_NAME):
            return await call_next(request)

        cookie_token = request.cookies.get(settings.CSRF_COOKIE_NAME)
        header_token = request.headers.get(settings.CSRF_HEADER_NAME)

        if not csrf_tokens_match(cookie_token, header_token):
            logger.warning(
                "CSRF 검증 실패: %s %s", request.method, request.url.path
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "CSRF 토큰이 유효하지 않습니다. 새로고침 후 다시 시도하세요."},
            )

        return await call_next(request)
