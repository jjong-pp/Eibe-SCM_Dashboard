@echo off
REM ---------------------------------------------------------------------------
REM EIBE Unified Platform - local launcher
REM
REM NOTE: This file is intentionally ASCII-only. cmd.exe reads batch files using
REM the active console codepage (cp949 on Korean Windows), so non-ASCII text
REM here can break parsing regardless of how the file is saved.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

if not exist ".venv" (
    echo [1/4] Creating virtual environment...
    python -m venv .venv || goto :failed
) else (
    echo [1/4] Virtual environment found.
)

echo [2/4] Installing dependencies...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip || goto :failed
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || goto :failed

echo [3/4] Applying database migrations...
".venv\Scripts\python.exe" -m alembic upgrade head || goto :failed

echo [4/4] Starting server on http://localhost:8000
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
goto :eof

:failed
echo.
echo Startup failed. See the message above.
pause
exit /b 1
