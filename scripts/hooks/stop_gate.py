"""Stop / SubagentStop: 코드가 바뀌었으면 전체 검증(정적 + ruff + pytest)을 돌린다.

실패하면 decision=block으로 턴을 끝내지 못하게 하고 실패 내용을 모델에 돌려준다.
연속 실패가 MAX_ATTEMPTS를 넘으면 막지 않고 사용자에게 알린다 (무한 루프 방지).
같은 내용으로 이미 통과했으면 다시 돌리지 않는다.
"""

import hashlib
import sys
from datetime import datetime

from _common import (
    ROOT, append_log, changed_files, emit, git, is_code, load_state, read_input, run_verify, save_state,
)

BUILDERS = {"front", "back", "data"}
MAX_ATTEMPTS = 3


def fingerprint(files: list) -> str:
    h = hashlib.sha256(git("status", "--porcelain").encode("utf-8"))
    for f in sorted(files):
        p = ROOT / f
        if p.is_file():
            h.update(f.encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def main() -> int:
    data = read_input()
    event = data.get("hook_event_name", "Stop")
    agent = data.get("agent_type") or data.get("subagent_type") or ""
    if event == "SubagentStop" and agent not in BUILDERS:
        return 0

    files = [f for f in changed_files() if is_code(f)]
    if not files:
        return 0
    fp = fingerprint(files)
    state = load_state("gate.json")
    if state.get("passed_fp") == fp:
        return 0

    code, out = run_verify("--tests")
    record = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event, "agent": agent or "main",
              "fp": fp, "files": files[:30]}
    if code == 0:
        save_state("gate.json", {"passed_fp": fp, "attempts": 0})
        append_log("verify-log.jsonl", {**record, "result": "pass"})
        return 0

    attempts = int(state.get("attempts", 0)) + 1
    append_log("verify-log.jsonl", {**record, "result": "fail", "attempt": attempts})
    if attempts > MAX_ATTEMPTS:
        save_state("gate.json", {"attempts": 0})
        emit({"systemMessage": f"[stop_gate] 검증 {MAX_ATTEMPTS}회 연속 실패. 작업을 멈추고 사용자 확인 필요.\n{out[-800:]}"})
        return 0

    save_state("gate.json", {"attempts": attempts})
    emit({
        "decision": "block",
        "reason": f"[stop_gate] 검증 실패 ({attempts}/{MAX_ATTEMPTS}). 원인을 고친 뒤 끝낸다. "
                  f"테스트 삭제·약화 금지.\n{out[-2500:]}",
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
