"""
비밀번호 해싱 · JWT 발급/검증 · CSRF 토큰.

구 버전 대비 변경점:
  - SECRET_KEY 하드코딩 제거 → settings 경유
  - python-jose → PyJWT (jose 3.3.0 은 2021년 이후 사실상 미유지보수이며
    알고리즘 혼동/DoS 취약점 이력이 있다)
  - 토큰 저장 위치를 localStorage → httpOnly 쿠키로 옮기므로,
    CSRF 이중 제출(double-submit) 토큰을 함께 발급한다.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.config import settings

# bcrypt 는 72바이트를 넘는 입력을 조용히 자르거나 거부한다.
# 긴 비밀번호를 SHA-256 으로 먼저 압축해 길이에 관계없이 전체를 반영한다.
_BCRYPT_MAX_BYTES = 72


def _prepare_password(password: str) -> bytes:
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        return hashlib.sha256(raw).hexdigest().encode("ascii")
    return raw


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare_password(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            _prepare_password(password), password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        # 손상된 해시 — 검증 실패로 처리한다.
        return False


def create_access_token(
    subject: str,
    role: str,
    user_id: int,
    expires_delta: timedelta | None = None,
) -> str:
    now = datetime.now(UTC)
    expire = now + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {
        "sub": subject,
        "uid": user_id,
        "role": role,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """유효하면 페이로드를, 아니면 None 을 돌려준다.

    만료·서명 불일치·형식 오류를 구분하지 않는다. 호출부에 노출해봐야
    공격자에게 정보를 줄 뿐이다.
    """
    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],  # 알고리즘 고정 — 혼동 공격 차단
        )
    except jwt.PyJWTError:
        return None


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_tokens_match(cookie_token: str | None, header_token: str | None) -> bool:
    """타이밍 공격에 안전한 비교."""
    if not cookie_token or not header_token:
        return False
    return secrets.compare_digest(cookie_token, header_token)
