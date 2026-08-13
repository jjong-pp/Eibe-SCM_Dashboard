"""
EIBE Unified Platform — 애플리케이션 진입점.

구 버전 대비 변경점:
  - APScheduler 및 자동 스냅샷 백업 제거 (인프로세스 스케줄러는 인스턴스가
    늘어나면 중복 실행되고 서버리스에서는 아예 동작하지 않는다. 백업은
    Cloud SQL 자동 백업/PITR 로 대체한다.)
  - 스키마 생성 책임을 create_all() 에서 Alembic 으로 이관
  - 기본 관리자 자동 생성(admin/admin) 제거 — 명시적 설정이 있을 때만 생성
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.config import settings
from app.core.logging import configure_logging
from app.core.middleware import CsrfMiddleware, RequestIdMiddleware
from app.core.security import hash_password
from app.database import SessionLocal
from app.models.auth import Role, User
from app.routers import auth as auth_router
from app.routers import system as system_router

configure_logging()
logger = logging.getLogger(__name__)


def _bootstrap_admin() -> None:
    """최초 관리자 계정 생성.

    구 버전은 서버가 뜰 때마다 admin/admin 을 만들었다. 배포되면 그대로
    취약점이 되므로, 비밀번호가 명시적으로 설정된 경우에만 생성한다.
    """
    if not settings.BOOTSTRAP_ADMIN_PASSWORD:
        with SessionLocal() as db:
            if db.query(User.id).first() is None:
                logger.warning(
                    "사용자 계정이 없습니다. EIBE_BOOTSTRAP_ADMIN_PASSWORD 를 설정하고 "
                    "재시작하거나 `python -m scripts.create_admin` 을 실행하세요."
                )
        return

    with SessionLocal() as db:
        username = settings.BOOTSTRAP_ADMIN_USERNAME
        if db.query(User).filter(User.username == username).first():
            return

        db.add(
            User(
                username=username,
                password_hash=hash_password(settings.BOOTSTRAP_ADMIN_PASSWORD),
                name=settings.BOOTSTRAP_ADMIN_NAME,
                role=Role.ADMIN,
            )
        )
        db.commit()
        logger.info("최초 관리자 계정을 생성했습니다: %s", username)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info(
        "%s v%s 기동 — env=%s dialect=%s",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.ENV,
        "sqlite" if settings.is_sqlite else "postgresql",
    )
    try:
        _bootstrap_admin()
    except SQLAlchemyError:
        # 마이그레이션 전이면 테이블이 없다. 기동 자체를 막지는 않는다.
        logger.exception(
            "관리자 부트스트랩 실패 — `alembic upgrade head` 를 먼저 실행했는지 확인하세요."
        )
    yield
    logger.info("종료합니다.")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="SCM · Sales Hub 통합 플랫폼",
        lifespan=lifespan,
        # 운영 환경에서는 API 문서를 노출하지 않는다.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    # 미들웨어는 등록 역순으로 실행된다 — 요청 ID 가 가장 바깥이어야
    # CSRF 거부 로그에도 ID 가 찍힌다.
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(RequestIdMiddleware)

    if settings.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,  # 쿠키 인증이므로 필수
            allow_methods=["*"],
            allow_headers=["*"],
        )

    _register_exception_handlers(app)

    app.include_router(system_router.public_router)
    app.include_router(system_router.router)
    app.include_router(auth_router.router)

    return app


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(IntegrityError)
    async def _integrity(request: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("무결성 제약 위반: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "이미 존재하거나 참조 중인 데이터입니다."},
        )

    @app.exception_handler(SQLAlchemyError)
    async def _sqlalchemy(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("DB 오류")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "데이터베이스 처리 중 오류가 발생했습니다."},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("처리되지 않은 오류")
        # 운영에서는 스택트레이스나 예외 메시지를 노출하지 않는다.
        detail = str(exc) if settings.DEBUG else "서버 오류가 발생했습니다."
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": detail},
        )


app = create_app()
