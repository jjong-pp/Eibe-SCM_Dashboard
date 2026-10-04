"""SessionStart: 새 세션에 스쿼드 현황을 짧게 주입한다 (진행 중 작업, 최근 검증, police 경고)."""

import json
import re
import sys

from _common import ROOT, STATE, emit, load_state

SQUAD = ROOT / ".squad"


def backlog_lines() -> list:
    try:
        items = json.loads((SQUAD / "backlog.json").read_text(encoding="utf-8")).get("tasks", [])
    except (OSError, ValueError):
        return ["backlog.json 읽기 실패"]
    open_items = [t for t in items if t.get("status") != "done"]
    lines = [
        f"- {t['id']} [{t.get('status')}/{t.get('size')}] {t.get('title')} ({','.join(t.get('owner', []))})"
        for t in open_items[:8]
    ]
    if len(open_items) > 8:
        lines.append(f"- 외 {len(open_items) - 8}건 (python scripts/squad.py status)")
    return lines or ["- 열린 작업 없음"]


def last_verify() -> str:
    log = STATE / "verify-log.jsonl"
    try:
        last = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
        return f"{last['result']} ({last['ts']}, {last['agent']})"
    except (OSError, ValueError, IndexError, KeyError):
        return "기록 없음"


def police_warnings() -> int:
    try:
        text = (SQUAD / "reports" / "police-log.md").read_text(encoding="utf-8")
    except OSError:
        return 0
    return sum(1 for ln in text.splitlines() if "| 미해결 |" in ln)


def handoff_lines() -> list:
    """이전현황.md의 머리 줄과 '다음 채팅에서 할 일' 앞부분 (기기 간 인계)."""
    try:
        text = (ROOT / "이전현황.md").read_text(encoding="utf-8")
    except OSError:
        return []
    stamp = next((ln.strip("> ").strip() for ln in text.splitlines() if ln.startswith("> 갱신")), "")
    m = re.search(r"^## \d+\. 다음 채팅에서 할 일\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    todo = [ln for ln in (m.group(1).splitlines() if m else []) if re.match(r"^\d+\. ", ln)][:5]
    return [f"[이전현황] {stamp} -> 이전현황.md, resume 스킬 B 절차로 시작", *todo]


def main() -> int:
    attempts = load_state("gate.json").get("attempts", 0)
    lines = [*handoff_lines(), "[squad] 현황 (상세: .squad/)", "열린 작업:", *backlog_lines(),
             f"최근 검증: {last_verify()}"]
    if attempts:
        lines.append(f"검증 연속 실패 {attempts}회 진행 중")
    warnings = police_warnings()
    if warnings:
        lines.append(f"police 미해결 경고 {warnings}건 -> .squad/reports/police-log.md")
    emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(lines)}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
