"""
SQLite 연결 및 SQLAlchemy ORM 설정 모듈
- 파일 기반 경량 데이터베이스 (data/local_erp.db)
- 별도 DB 엔진 데몬 프로세스 불필요
"""

import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

# ── 데이터베이스 파일 경로 ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
# SCM_DB_PATH: 테스트·QA용 별도 DB 지정 (미지정 시 운영 DB)
DB_PATH = os.environ.get("SCM_DB_PATH") or os.path.join(DATA_DIR, "local_erp.db")
BACKUP_DIR = os.environ.get("SCM_BACKUP_DIR") or os.path.join(DATA_DIR, "backups")

# data/ 및 backups/ 디렉토리 자동 생성
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

# ── SQLAlchemy 엔진 설정 ───────────────────────────────────────────────
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},  # FastAPI 비동기 환경 호환
    echo=False,
)


# SQLite 외래키 제약 조건 강제 활성화
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging 성능 최적화
    cursor.close()


# ── 세션 팩토리 ────────────────────────────────────────────────────────
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ── ORM Base 클래스 ────────────────────────────────────────────────────
Base = declarative_base()


def get_db():
    """FastAPI Depends 의존성 주입용 DB 세션 제너레이터"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """애플리케이션 시작 시 모든 테이블 자동 생성"""
    from app import models  # noqa: F401 - 모델 등록을 위한 임포트

    Base.metadata.create_all(bind=engine)
