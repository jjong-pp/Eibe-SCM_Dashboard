"""
구조화 로깅 설정.

구 버전은 전부 print() 였다. 배포 환경에서는 요청 단위 추적이 불가능하므로
표준 logging 으로 옮기고, 요청 ID 를 컨텍스트로 붙인다.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

from app.config import settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging() -> None:
    # stdout/stderr 의 UTF-8 고정은 app/__init__.py 에서 이미 처리된다.
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL)

    # 접근 로그는 우리 포맷과 중복되므로 낮춘다.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DB_ECHO else logging.WARNING
    )
