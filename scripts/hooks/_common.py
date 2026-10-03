"""훅 공통 유틸. Claude Code와 Codex 양쪽 훅이 같은 스크립트를 쓴다 (표준 라이브러리만)."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".squad" / "state"
CODE_PREFIXES = ("app/", "web/", "tests/", "scripts/")
CODE_FILES = ("seed_data.py", "requirements.txt", "requirements-dev.txt", "pyproject.toml")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def read_input() -> dict:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        return {}


def git(*args) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return proc.stdout


def changed_files() -> list:
    """작업 트리에서 수정·추가된 파일 (삭제 제외)."""
    files = []
    for line in git("status", "--porcelain", "-uall").splitlines():
        if len(line) < 4 or line[1] == "D" or line[0] == "D":
            continue
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        files.append(path)
    return files


def is_code(path: str) -> bool:
    return path.startswith(CODE_PREFIXES) or path in CODE_FILES


def run_verify(*args) -> tuple:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify.py"), *args], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def load_state(name: str) -> dict:
    p = STATE / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(name: str, data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def append_log(name: str, record: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / name).open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))
