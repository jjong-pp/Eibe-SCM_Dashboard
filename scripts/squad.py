"""스쿼드 운영 CLI (표준 라이브러리만). Claude Code·Codex 어느 쪽 세션에서든 같은 명령을 쓴다.

  python scripts/squad.py status
  python scripts/squad.py new "제목" --size M --owner back,front
  python scripts/squad.py set T-004 status=doing
  python scripts/squad.py police T-004 [--judge]       # 결정적 감사 D1~D6 (+ 교차 모델 판정 J1~J3)
  python scripts/squad.py review T-004 [--engine codex|claude]
  python scripts/squad.py close T-004
  python scripts/squad.py qa-server start|stop [--port 8765]
"""

import argparse
import fnmatch
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQUAD = ROOT / ".squad"
BACKLOG = SQUAD / "backlog.json"
CONTRACTS = SQUAD / "contracts"
REPORTS = SQUAD / "reports"
STATE = SQUAD / "state"
POLICE_LOG = REPORTS / "police-log.md"
ROLES = ROOT / ".agents" / "roles"

sys.path.insert(0, str(ROOT / "scripts" / "hooks"))
from stop_gate import fingerprint  # noqa: E402
from _common import changed_files, is_code, load_state  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── 공통 ──────────────────────────────────────────────────────────────
def sh(*args, check=False, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check, **kw)


def git(*args) -> str:
    return sh("git", *args).stdout


def load_backlog() -> dict:
    return json.loads(BACKLOG.read_text(encoding="utf-8"))


def save_backlog(data: dict) -> None:
    BACKLOG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_task(data: dict, task_id: str) -> dict:
    for t in data["tasks"]:
        if t["id"] == task_id:
            return t
    sys.exit(f"작업 없음: {task_id}")


def contract_path(task_id: str) -> Path:
    return CONTRACTS / f"{task_id}.md"


def parse_contract(task_id: str) -> dict:
    p = contract_path(task_id)
    if not p.exists():
        return {"exists": False, "allowed": [], "base": "", "text": ""}
    text = p.read_text(encoding="utf-8")
    base = re.search(r"^base:\s*(\S+)", text, re.M)
    allowed, in_allowed = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            in_allowed = line.strip() == "## allowed_files"
            continue
        m = re.match(r"\s+-\s+(\S.*)$", line)
        if in_allowed and m:
            allowed.append(m.group(1).strip())
    return {"exists": True, "allowed": allowed, "base": base.group(1) if base else "", "text": text}


def venv_python() -> str:
    for cand in (ROOT / "venv" / "Scripts" / "python.exe", ROOT / "venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


def now() -> str:
    return datetime.now().strftime("%m-%d %H:%M")


# ── 교차 모델 실행 ────────────────────────────────────────────────────
def find_cli(name: str) -> str:
    env = os.environ.get(f"{name.upper()}_CLI")
    if env and Path(env).exists():
        return env
    found = shutil.which(name)
    if found:
        return found
    patterns = {
        "codex": [os.path.expandvars(r"%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe")],
        "claude": [os.path.expandvars(r"%APPDATA%\Claude\claude-code\*\*\claude.exe"),
                   os.path.expanduser("~/.local/bin/claude")],
    }[name]
    hits = [h for pat in patterns for h in glob.glob(pat)]
    return max(hits, key=os.path.getmtime) if hits else ""


def default_engine() -> str:
    """빌더와 다른 계열을 고른다. Claude 세션이면 codex, 그 외는 claude."""
    return "codex" if os.environ.get("CLAUDECODE") == "1" else "claude"


def role_instructions(role: str) -> str:
    import tomllib
    data = tomllib.loads((ROLES / f"{role}.toml").read_text(encoding="utf-8"))
    return data["body"]["instructions"]


def run_engine(engine: str, prompt: str, out_file: Path, writable: bool) -> int:
    cli = find_cli(engine)
    if not cli:
        print(f"{engine} CLI를 찾지 못함. {engine.upper()}_CLI 환경변수로 경로 지정,")
        print("또는 같은 계열 서브에이전트로 실행하고 리포트에 'same-family'를 표기한다.")
        return 2
    if engine == "codex":
        cmd = [cli, "exec", "-C", str(ROOT), "-s", "workspace-write" if writable else "read-only",
               "-c", 'model_reasoning_effort="high"', "-o", str(out_file), "-"]
        if writable:
            cmd[6:6] = ["-c", "sandbox_workspace_write.network_access=true"]
        proc = subprocess.run(cmd, cwd=ROOT, input=prompt, text=True, encoding="utf-8", errors="replace")
        return proc.returncode
    agent = "reviewer" if writable else "police"
    tools = "Read Grep Glob Bash PowerShell" if writable else "Read Grep Glob"
    proc = subprocess.run([cli, "-p", "--agent", agent, "--allowedTools", *tools.split()], cwd=ROOT,
                          input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out_file.write_text(proc.stdout, encoding="utf-8")
    if "Not logged in" in proc.stdout:
        print("claude CLI 로그인 필요: 터미널에서 claude 실행 후 /login (한 번만)")
    elif proc.returncode != 0:
        print(proc.stderr[-1500:])
    return proc.returncode


def code_snapshot() -> dict:
    files = [f for f in changed_files() if not f.startswith(".squad/")]
    return {f: (ROOT / f).stat().st_mtime for f in files if (ROOT / f).is_file()}


# ── 명령 ──────────────────────────────────────────────────────────────
def cmd_status(_args) -> int:
    data = load_backlog()
    print(f"{'ID':6} {'상태':8} {'크기':3} {'통과':4} {'담당':14} 제목")
    for t in data["tasks"]:
        print(f"{t['id']:6} {t.get('status', ''):8} {t.get('size', ''):3} {('Y' if t.get('passes') else '-'):4} "
              f"{','.join(t.get('owner', [])):14} {t['title']}")
    gate = load_state("gate.json")
    if gate.get("attempts"):
        print(f"\n검증 연속 실패: {gate['attempts']}회")
    return 0


def cmd_new(args) -> int:
    data = load_backlog()
    task_id = f"T-{data['next_id']:03d}"
    owner = [o.strip() for o in args.owner.split(",") if o.strip()]
    task = {"id": task_id, "title": args.title, "size": args.size, "owner": owner, "status": "todo",
            "passes": False, "created": date.today().isoformat()}
    if args.size in ("M", "L"):
        tpl = (CONTRACTS / "_template.md").read_text(encoding="utf-8")
        base = git("rev-parse", "--short", "HEAD").strip()
        contract_path(task_id).write_text(tpl.format(
            id=task_id, title=args.title, base=base, size=args.size,
            created=date.today().isoformat(), owner=" → ".join(owner)), encoding="utf-8")
        task["contract"] = f".squad/contracts/{task_id}.md"
    data["tasks"].append(task)
    data["next_id"] += 1
    save_backlog(data)
    print(task_id, task.get("contract", "(S 작업: 계약서 없음)"))
    return 0


def cmd_set(args) -> int:
    data = load_backlog()
    task = find_task(data, args.id)
    for kv in args.pairs:
        key, _, value = kv.partition("=")
        if key == "passes":
            sys.exit("passes는 close 명령으로만 바꾼다")
        task[key] = value.split(",") if key == "owner" else value
    save_backlog(data)
    print(json.dumps(task, ensure_ascii=False))
    return 0


def police_checks(task_id: str) -> list:
    """결정적 검사. (항목, 근거) 위반 목록을 돌려준다."""
    c = parse_contract(task_id)
    base = c["base"] or "HEAD"
    violations = []

    changed = set(git("diff", "--name-only", base).split()) | set(
        git("ls-files", "--others", "--exclude-standard").split())
    changed = {f for f in changed if not f.startswith(".squad/")}

    # D1 파일 범위
    if c["exists"]:
        outside = sorted(f for f in changed if not any(fnmatch.fnmatch(f, pat) for pat in c["allowed"]))
        if outside:
            violations.append(("D1 파일 범위", "계약 밖 수정: " + ", ".join(outside[:10])))

    # D2 테스트 약화
    def count(pattern: str, at_base: bool) -> int:
        total = 0
        if at_base:
            for f in git("ls-tree", "-r", "--name-only", base, "tests/").split():
                if f.endswith(".py"):
                    total += len(re.findall(pattern, git("show", f"{base}:{f}"), re.M))
        else:
            for p in (ROOT / "tests").rglob("*.py"):
                total += len(re.findall(pattern, p.read_text(encoding="utf-8", errors="replace"), re.M))
        return total

    for label, pattern in (("테스트 함수", r"^\s*def test_"), ("assert", r"^\s*assert\b")):
        before, after = count(pattern, True), count(pattern, False)
        if after < before:
            violations.append(("D2 테스트 약화", f"{label} {before} → {after}"))
    added = [ln for ln in git("diff", base, "--", "tests/").splitlines() if ln.startswith("+")]
    if any(re.search(r"pytest\.mark\.(skip|xfail)|pytest\.skip\(", ln) for ln in added):
        violations.append(("D2 테스트 약화", "skip/xfail 추가"))

    # D3·D4 금지 의존성·UI 패턴 (정적 검사)
    proc = sh(sys.executable, str(ROOT / "scripts" / "verify.py"))
    if proc.returncode != 0:
        violations.append(("D3/D4 정적 검사", proc.stdout.strip().splitlines()[0]))

    # D5 검증 실행 여부: 현재 작업 트리가 stop_gate를 통과했는지
    code_files = [f for f in changed_files() if is_code(f)]
    if code_files and load_state("gate.json").get("passed_fp") != fingerprint(code_files):
        violations.append(("D5 검증 미실행", "현재 변경분이 stop_gate 검증을 통과한 기록 없음"))

    # D6 계약 증거
    if c["exists"]:
        acs = re.findall(r"^- \[( |x)\] (AC\d+)\..*?\| 증거:(.*)$", c["text"], re.M)
        missing = [ac for mark, ac, ev in acs if mark != "x" or not ev.strip()]
        if not acs:
            violations.append(("D6 계약 증거", "수용 기준 항목 없음"))
        elif missing:
            violations.append(("D6 계약 증거", "미완료/증거 없음: " + ", ".join(missing)))

    # D7 baseline 증가
    base_added = [ln for ln in git("diff", base, "--", ".squad/verify-baseline.txt").splitlines()
                  if ln.startswith("+") and not ln.startswith("+++") and not ln.startswith("+#")]
    if base_added:
        violations.append(("D7 baseline 증가", f"기존 결함 목록에 {len(base_added)}건 추가 (사용자 승인 필요)"))
    return violations


def append_police_log(task_id: str, rows: list) -> None:
    text = POLICE_LOG.read_text(encoding="utf-8")
    text = re.sub(rf"(\| {re.escape(task_id)} \|.*)\| 미해결 \|$", r"\1| 재검사됨 |", text, flags=re.M)
    for item, result, reason in rows:
        status = "통과" if result == "PASS" else "미해결"
        reason = reason.replace("|", "/")
        text += f"| {now()} | {task_id} | {item} | {result} | {reason} | {status} |\n"
    POLICE_LOG.write_text(text, encoding="utf-8")


def cmd_police(args) -> int:
    data = load_backlog()
    task = find_task(data, args.id)
    violations = police_checks(args.id)

    if args.judge and not violations:
        REPORTS.mkdir(exist_ok=True)
        out = REPORTS / f"{args.id}-police.md"
        prompt = (f"{role_instructions('police')}\n\n작업: {args.id}\n계약서: {contract_path(args.id).as_posix()}\n"
                  f"base 커밋: {parse_contract(args.id)['base']}\n"
                  "결정적 검사 D1~D7은 이미 통과했다. squad.py를 실행하지 말고 J1~J3만 판정한다. "
                  "마지막 메시지 첫 줄은 'VERDICT: PASS' 또는 'VERDICT: FAIL'.")
        run_engine(args.engine or default_engine(), prompt, out, writable=False)
        verdict = out.read_text(encoding="utf-8") if out.exists() else ""
        if "VERDICT: FAIL" in verdict:
            violations.append(("J 판정", f"교차 모델 판정 실패 -> {out.relative_to(ROOT).as_posix()}"))

    if not violations:
        append_police_log(args.id, [("전체", "PASS", "D1~D7" + (" + J" if args.judge else ""))])
        task["police"] = "pass"
        save_backlog(data)
        print(f"[police] {args.id} 통과")
        return 0

    strikes = int(task.get("police_strikes", 0)) + 1
    task["police_strikes"] = strikes
    level = "경고1" if strikes == 1 else "경고2"
    if strikes >= 2:
        task["status"] = "blocked"
    task["police"] = level
    save_backlog(data)
    append_police_log(args.id, [(item, level, reason) for item, reason in violations])
    print(f"[police] {args.id} {level} ({len(violations)}건)")
    for item, reason in violations:
        print(f"- {item}: {reason}")
    if strikes >= 2:
        print("[police] 재위반: 작업 중단(blocked). PM은 사용자에게 보고하고 계약을 다시 쓴다.")
    else:
        print("[police] 담당 에이전트에 위 근거를 전달해 재시도한다.")
    return 1


def cmd_review(args) -> int:
    find_task(load_backlog(), args.id)
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"{args.id}-review.md"
    engine = args.engine or default_engine()
    prompt = (f"{role_instructions('reviewer')}\n\n작업: {args.id}\n"
              f"계약서: {contract_path(args.id).as_posix()}\n"
              "절차: .agents/skills/qa-review/SKILL.md 를 먼저 읽고 그대로 따른다.\n"
              "코드를 수정하지 않는다. 리포트 전체를 마지막 메시지로 출력한다.")
    before = code_snapshot()
    print(f"[review] {engine} 실행 중 ... (결과: {out.relative_to(ROOT).as_posix()})")
    code = run_engine(engine, prompt, out, writable=True)
    if code_snapshot() != before:
        append_police_log(args.id, [("reviewer 권한", "경고1", "reviewer 실행 중 코드 파일이 변경됨")])
        print("[review] 경고: reviewer 실행 중 코드 파일이 바뀜. police-log 기록")
    if out.exists():
        verdict = re.search(r"판정:\s*(PASS|FAIL)", out.read_text(encoding="utf-8"))
        print(f"[review] 판정: {verdict.group(1) if verdict else '판정 줄 없음'} (engine={engine})")
    return code


def cmd_close(args) -> int:
    data = load_backlog()
    task = find_task(data, args.id)
    if task.get("size") in ("M", "L"):
        review = REPORTS / f"{args.id}-review.md"
        if not review.exists() or not re.search(r"판정:\s*PASS", review.read_text(encoding="utf-8")):
            sys.exit("reviewer PASS 리포트 없음")
        if task.get("police") != "pass":
            sys.exit("police 통과 기록 없음")
    task["passes"] = True
    task["status"] = "done"
    task["closed"] = date.today().isoformat()
    save_backlog(data)
    print(f"{args.id} 완료")
    return 0


def cmd_qa_server(args) -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    pid_file = STATE / "qa-server.pid"
    if args.action == "stop":
        if not pid_file.exists():
            print("실행 중인 QA 서버 없음")
            return 0
        pid = pid_file.read_text().strip()
        if os.name == "nt":
            sh("taskkill", "/PID", pid, "/T", "/F")
        else:
            sh("kill", pid)
        pid_file.unlink()
        print(f"QA 서버 종료 (pid {pid})")
        return 0

    env = {**os.environ, "SCM_DB_PATH": str(STATE / "qa.db"), "SCM_BACKUP_DIR": str(STATE / "qa-backups")}
    for suffix in ("", "-shm", "-wal"):
        Path(str(STATE / "qa.db") + suffix).unlink(missing_ok=True)
    seed = subprocess.run([venv_python(), "-c", "import random; random.seed(42); import seed_data; seed_data.seed()"],
                          cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if seed.returncode != 0:
        print(seed.stderr[-1500:])
        return 1
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS) if os.name == "nt" else 0
    log = open(STATE / "qa-server.log", "w", encoding="utf-8")
    proc = subprocess.Popen([venv_python(), "-m", "uvicorn", "app.main:app", "--port", str(args.port)],
                            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    pid_file.write_text(str(proc.pid))
    print(f"QA 서버 시작: http://127.0.0.1:{args.port} (pid {proc.pid}, DB .squad/state/qa.db, 계정 admin/admin)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="스쿼드 운영 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("new")
    p.add_argument("title")
    p.add_argument("--size", choices=["S", "M", "L"], required=True)
    p.add_argument("--owner", required=True, help="front,back,data")
    p = sub.add_parser("set")
    p.add_argument("id")
    p.add_argument("pairs", nargs="+", help="key=value")
    p = sub.add_parser("police")
    p.add_argument("id")
    p.add_argument("--judge", action="store_true", help="교차 모델로 J1~J3 판정")
    p.add_argument("--engine", choices=["codex", "claude"])
    p = sub.add_parser("review")
    p.add_argument("id")
    p.add_argument("--engine", choices=["codex", "claude"])
    p = sub.add_parser("close")
    p.add_argument("id")
    p = sub.add_parser("qa-server")
    p.add_argument("action", choices=["start", "stop"])
    p.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    return {"status": cmd_status, "new": cmd_new, "set": cmd_set, "police": cmd_police, "review": cmd_review,
            "close": cmd_close, "qa-server": cmd_qa_server}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
