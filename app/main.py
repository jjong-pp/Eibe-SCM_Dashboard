"""
FastAPI 메인 엔드포인트 및 라우팅 제어 모듈 (v3.0) - 리팩토링 됨
- 라우터 구조로 분할됨 (app/routers)
- 통합 예외 처리기 적용
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app.database import init_db, BASE_DIR
from app.models import UserAccount
from app.core.auth import get_password_hash
from app.core.snapshot import start_scheduler, stop_scheduler

from app.routers import views, auth, system, users, master, pipeline, inventory

@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작 시 DB 테이블 자동 생성 및 기본 관리자 계정 초기화"""
    init_db()
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        admin = db.query(UserAccount).filter(UserAccount.username == "admin").first()
        if not admin:
            pw_hash = get_password_hash("admin")
            db.add(
                UserAccount(
                    username="admin",
                    password_hash=pw_hash,
                    role="ADMIN",
                    name="시스템 관리자",
                )
            )
            db.commit()
            print("[INIT] Default admin account created (admin/admin)")
    except Exception as e:
        print("Initialization error:", e)
        db.rollback()
    finally:
        db.close()

    start_scheduler()
    yield
    stop_scheduler()

app = FastAPI(
    title="SCM ERP Dashboard",
    description="독립형 로컬 SCM ERP 시스템 — 3NF 관계형 스키마 v3",
    version="3.0.0",
    lifespan=lifespan,
)

# ── 예외 처리기 (Global Exception Handlers) ───────────────────────────────
@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    print(f"IntegrityError: {exc}")
    return JSONResponse(
        status_code=400,
        content={"detail": "데이터 제약 조건 위반 오류가 발생했습니다. (예: 이미 사용 중이거나 중복된 데이터)"},
    )

@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    print(f"SQLAlchemyError: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "데이터베이스 처리 중 오류가 발생했습니다."},
    )

# ── 정적 파일 서빙 설정 ──────────────────────────────────────────────
WEB_DIR = os.path.join(BASE_DIR, "web")
STATIC_DIR = os.path.join(WEB_DIR, "static")

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ── 라우터 등록 ────────────────────────────────────────────────────────
app.include_router(views.router)
app.include_router(auth.router)
app.include_router(system.router)
app.include_router(users.router)
app.include_router(master.router)
app.include_router(pipeline.router)
app.include_router(inventory.router)
