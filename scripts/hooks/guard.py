"""PreToolUse: 되돌리기 어려운 셸 명령을 실행 전에 차단한다. 차단 시 exit 2 + stderr 사유."""

import re
import sys

from _common import read_input

RULES = [
    (r"\bgit\s+push\b.*(\s-f\b|--force)", "강제 push 금지. 사용자에게 직접 요청"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard 금지. 변경을 버려야 하면 사용자 확인"),
    (r"\bgit\s+clean\s+-\w*f", "git clean -f 금지 (추적 안 된 파일 영구 삭제)"),
    (r"\bgit\s+checkout\s+--\s+\.", "작업 트리 전체 되돌리기 금지"),
    (r"--no-verify\b", "훅 우회(--no-verify) 금지"),
    (r"\b(rm|del|erase|Remove-Item)\b[^\n|;&]*local_erp\.db", "운영 DB 삭제 금지"),
    (r"\b(rm|del|Remove-Item)\b[^\n|;&]*data[\\/]+backups", "백업 삭제 금지"),
    (r"\brm\s+-\w*r\w*f?\s+(\.|/|~|\*|app|web|tests|data|\.git|\.squad|\.agents)(\s|/|$)", "주요 디렉터리 재귀 삭제 금지"),
    (r"\bRemove-Item\b[^\n]*-Recurse[^\n]*(app|web|tests|data|\.git|\.squad|\.agents)\b", "주요 디렉터리 재귀 삭제 금지"),
    (r"\bDROP\s+TABLE\b", "DROP TABLE 금지. 스키마 변경은 data 역할이 마이그레이션으로"),
]


def command_text(data: dict) -> str:
    tool_input = data.get("tool_input") or {}
    cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else tool_input
    if isinstance(cmd, list):
        cmd = " ".join(map(str, cmd))
    return str(cmd)


def main() -> int:
    cmd = command_text(read_input())
    if not cmd:
        return 0
    for pattern, reason in RULES:
        if re.search(pattern, cmd, re.I):
            print(f"[guard] 차단: {reason}\n명령: {cmd[:200]}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
