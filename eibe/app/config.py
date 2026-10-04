"""
애플리케이션 설정 — 모든 환경값의 단일 출처.

코드에는 시크릿을 두지 않는다. 값은 `.env` 또는 실제 환경변수에서만 온다.
(구 버전은 app/core/auth.py 에 SECRET_KEY 가 하드코딩되어 있었다.)
"""

from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# eibe/ — 저장소 루트로 승격되면 그대로 프로젝트 루트가 된다.
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

Env = Literal["local", "staging", "production"]

# 부트스트랩 관리자에 허용하지 않는 비밀번호 (구 버전 기본값 admin/admin 재발 방지)
_WEAK_PASSWORDS = {"admin", "password", "1234", "12345678", "changeme", "eibe"}
_MIN_PASSWORD_LENGTH = 10


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        env_prefix="EIBE_",
        extra="ignore",
        case_sensitive=False,
    )

    # ── 실행 환경 ────────────────────────────────────────────────────
    ENV: Env = "local"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    APP_NAME: str = "EIBE Unified Platform"
    APP_VERSION: str = "4.0.0"

    # ── 데이터베이스 ─────────────────────────────────────────────────
    DATABASE_URL: str = ""
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # ── 인증 ─────────────────────────────────────────────────────────
    SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720  # 12시간
    COOKIE_NAME: str = "eibe_session"
    CSRF_COOKIE_NAME: str = "eibe_csrf"
    CSRF_HEADER_NAME: str = "X-CSRF-Token"
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"

    # ── 최초 관리자 ──────────────────────────────────────────────────
    BOOTSTRAP_ADMIN_USERNAME: str = "admin"
    BOOTSTRAP_ADMIN_PASSWORD: str = ""
    BOOTSTRAP_ADMIN_NAME: str = "시스템 관리자"

    # ── 조직 ─────────────────────────────────────────────────────────
    STAFF_EMAIL_DOMAINS: str = ""
    CORS_ORIGINS: str = ""

    # ── 업로드 / 배치 ────────────────────────────────────────────────
    UPLOAD_MAX_MB: int = 20
    WRITE_BATCH_SIZE: int = 500

    # ── 표시 기본값 ──────────────────────────────────────────────────
    DEFAULT_LOCALE: str = "ko-KR"
    DEFAULT_TIMEZONE: str = "Asia/Seoul"
    DEFAULT_CURRENCY: str = "KRW"

    # ── 파생값 ───────────────────────────────────────────────────────

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def staff_domains(self) -> list[str]:
        """사내 이메일 도메인 목록. 항상 '@' 로 시작하도록 정규화."""
        return [
            d if d.startswith("@") else f"@{d}"
            for d in (
                part.strip().lower().lstrip("@")
                for part in self.STAFF_EMAIL_DOMAINS.split(",")
            )
            if d
        ]

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def upload_max_bytes(self) -> int:
        return self.UPLOAD_MAX_MB * 1024 * 1024

    # ── 검증 ─────────────────────────────────────────────────────────

    @field_validator("LOG_LEVEL")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        level = v.strip().upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"잘못된 LOG_LEVEL: {v}")
        return level

    @model_validator(mode="after")
    def _apply_defaults_and_guards(self) -> Settings:
        # DATABASE_URL 기본값 — 로컬 SQLite
        if not self.DATABASE_URL:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            object.__setattr__(
                self, "DATABASE_URL", f"sqlite:///{DATA_DIR / 'eibe.db'}"
            )

        if self.is_production:
            self._validate_production()
        elif not self.SECRET_KEY:
            # 로컬 편의: 임시 키를 생성한다. 재시작하면 세션이 만료되므로
            # 안전하고, 시크릿이 저장소로 새어나가지도 않는다.
            object.__setattr__(self, "SECRET_KEY", secrets.token_urlsafe(48))
            logger.warning(
                "EIBE_SECRET_KEY 미설정 — 임시 키를 생성했습니다. "
                "서버를 재시작하면 모든 세션이 만료됩니다."
            )

        return self

    def _validate_production(self) -> None:
        """production 에서만 강제하는 규칙. 로컬 개발을 막지 않는다."""
        problems: list[str] = []

        if not self.SECRET_KEY:
            problems.append("EIBE_SECRET_KEY 가 비어 있습니다.")
        elif len(self.SECRET_KEY) < 32:
            problems.append("EIBE_SECRET_KEY 는 32자 이상이어야 합니다.")

        if not self.COOKIE_SECURE:
            problems.append(
                "production 에서는 EIBE_COOKIE_SECURE=true 여야 합니다 (HTTPS 전용 쿠키)."
            )

        pw = self.BOOTSTRAP_ADMIN_PASSWORD
        if pw:
            if pw.lower() in _WEAK_PASSWORDS:
                problems.append("EIBE_BOOTSTRAP_ADMIN_PASSWORD 가 너무 흔합니다.")
            elif len(pw) < _MIN_PASSWORD_LENGTH:
                problems.append(
                    f"EIBE_BOOTSTRAP_ADMIN_PASSWORD 는 {_MIN_PASSWORD_LENGTH}자 이상이어야 합니다."
                )

        if self.DEBUG:
            problems.append("production 에서는 EIBE_DEBUG=false 여야 합니다.")

        if problems:
            raise ValueError(
                "production 설정 오류:\n  - " + "\n  - ".join(problems)
            )

    def sqlalchemy_kwargs(self) -> dict[str, Any]:
        """방언별 엔진 옵션. SQLite ↔ PostgreSQL 전환을 여기서 흡수한다."""
        kwargs: dict[str, Any] = {"echo": self.DB_ECHO, "future": True}

        if self.is_sqlite:
            # 단일 파일 DB — 커넥션 풀 설정이 의미 없다.
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs["pool_size"] = self.DB_POOL_SIZE
            kwargs["max_overflow"] = self.DB_MAX_OVERFLOW
            kwargs["pool_pre_ping"] = True  # 유휴 커넥션 끊김 방지

        return kwargs


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
