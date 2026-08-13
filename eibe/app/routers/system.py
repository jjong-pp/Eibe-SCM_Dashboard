"""시스템 상태 엔드포인트."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import require_admin
from app.database import get_db
from app.schemas.common import HealthResponse

# 공개 — 로드밸런서/모니터링이 인증 없이 호출한다.
public_router = APIRouter(prefix="/api/system", tags=["시스템"])

# 보호 — 관리자 전용. 라우터 기본 의존성으로 강제한다.
router = APIRouter(
    prefix="/api/system",
    tags=["시스템"],
    dependencies=[Depends(require_admin)],
)


@public_router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """헬스체크. 내부 상태를 노출하지 않는다."""
    return HealthResponse(
        status="ok",
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        env=settings.ENV,
    )


@router.get("/diagnostics")
def diagnostics(db: Session = Depends(get_db)) -> dict[str, object]:
    """DB 연결 상태와 방언 정보. 관리자 전용."""
    db.execute(text("SELECT 1"))
    return {
        "database_dialect": db.bind.dialect.name if db.bind else "unknown",
        "is_sqlite": settings.is_sqlite,
        "env": settings.ENV,
        "version": settings.APP_VERSION,
    }
