"""PostToolUse: 방금 수정한 파일만 빠르게 정적 검사한다. 문제가 있으면 exit 2로 모델에 즉시 반환."""

import re
import sys
from pathlib import Path

from _common import ROOT, changed_files, read_input, run_verify

CHECK_EXT = (".py", ".html", ".css", ".js")


def edited_paths(data: dict) -> list:
    tool_input = data.get("tool_input") or {}
    paths = []
    if isinstance(tool_input, dict):
        for key in ("file_path", "path", "notebook_path"):
            if tool_input.get(key):
                paths.append(str(tool_input[key]))
        text = " ".join(str(v) for v in tool_input.values() if isinstance(v, str))
    else:
        text = str(tool_input)
    # Codex apply_patch 형식
    paths += re.findall(r"\*\*\* (?:Add|Update) File: (.+)", text)
    if not paths:
        paths = changed_files()
    out = []
    for p in paths:
        path = Path(p.strip())
        if not path.is_absolute():
            path = ROOT / path
        try:
            rel = path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            continue
        if rel.endswith(CHECK_EXT) and not rel.startswith("venv/"):
            out.append(rel)
    return sorted(set(out))


def main() -> int:
    files = edited_paths(read_input())
    if not files:
        return 0
    code, out = run_verify("--files", *files)
    if code != 0:
        print(f"{out}\n수정한 파일의 검사 실패. 바로 고친다.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
