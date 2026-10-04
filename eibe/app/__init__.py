"""
EIBE Unified Platform.

프로세스 수준 I/O 설정을 여기서 먼저 처리한다. 이 모듈은 다른 app 하위
모듈보다 항상 먼저 로드되므로, 설정 로딩 중에 나오는 경고까지 UTF-8 로 찍힌다.
(Windows 한국어 환경의 기본 콘솔 인코딩은 cp949 라 한글이 깨진다.)
"""

from __future__ import annotations

import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
