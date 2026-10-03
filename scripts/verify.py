"""프로젝트 검증 스크립트. 훅과 police가 공통으로 호출한다 (표준 라이브러리만 사용).

사용:
  python scripts/verify.py                 # 정적 검사 전체
  python scripts/verify.py --tests         # 정적 검사 + ruff + pytest
  python scripts/verify.py --files a b     # 지정 파일만 (훅용, 빠름)
  python scripts/verify.py --write-baseline # 현재 정적 결함을 기존 결함으로 등록 (사용자 승인 후에만)
종료 코드: 0 통과 / 1 실패
기존 결함(.squad/verify-baseline.txt)은 실패로 치지 않는다. 고친 항목은 baseline에서 지운다.
"""

import argparse
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
CSS_FILE = WEB / "static" / "css" / "style.css"
BASELINE = ROOT / ".squad" / "verify-baseline.txt"

# 닫는 태그가 반드시 있어야 하는 요소 (생략 가능한 p, li, td, tr, option 등은 제외)
STRICT_TAGS = {
    "div", "section", "table", "thead", "tbody", "script", "style", "form", "select",
    "button", "aside", "main", "header", "footer", "nav", "ul", "ol", "span", "a",
    "label", "textarea", "svg", "canvas", "h1", "h2", "h3", "h4",
}
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u26FF\u2700-\u27BF\uFE0F]")
GRADIENT_RE = re.compile(r"(linear|radial|conic)-gradient\(")
KOREAN_WEEK_RE = re.compile(r"\d+\s*월\s*\d+\s*주")
FRAMEWORK_SRC_RE = re.compile(r"<script[^>]+src=[\"'][^\"']*(react|vue|angular|svelte)[^\"']*", re.I)
CSS_VAR_DEF_RE = re.compile(r"(--[\w-]+)\s*:")
CSS_VAR_SET_RE = re.compile(r"setProperty\(\s*['\"](--[\w-]+)")
CSS_VAR_USE_RE = re.compile(r"var\(\s*(--[\w-]+)\s*([,)])")
FORBIDDEN_PY = re.compile(
    r"^\s*(?:from|import)\s+(sklearn|torch|tensorflow|keras|statsmodels|prophet|xgboost|lightgbm)\b",
    re.M,
)
FORBIDDEN_REQ = re.compile(
    r"^\s*(scikit-learn|sklearn|torch|tensorflow|keras|statsmodels|prophet|xgboost|lightgbm)\b",
    re.M | re.I,
)


class _TagChecker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.ids = {}
        self.errors = []

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        for k, v in attrs:
            if k == "id" and v and "${" not in v and "{{" not in v:
                self.ids.setdefault(v, []).append(line)
        if tag in STRICT_TAGS:
            self.stack.append((tag, line))

    def handle_startendtag(self, tag, attrs):
        for k, v in attrs:
            if k == "id" and v:
                self.ids.setdefault(v, []).append(self.getpos()[0])

    def handle_endtag(self, tag):
        if tag not in STRICT_TAGS:
            return
        line = self.getpos()[0]
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
            return
        open_tags = [t for t, _ in self.stack]
        if tag in open_tags:
            while self.stack and self.stack[-1][0] != tag:
                t, ln = self.stack.pop()
                self.errors.append(f"<{t}> (line {ln}) 닫히지 않음")
            self.stack.pop()
        else:
            self.errors.append(f"</{tag}> (line {line}) 여는 태그 없음")


def rel(p: Path) -> str:
    return p.resolve().relative_to(ROOT).as_posix()


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def strip_comments(text: str, kind: str) -> str:
    """주석 안의 패턴은 검사하지 않는다 (줄 번호 유지를 위해 줄바꿈은 남김)."""
    keep_nl = lambda m: "\n" * m.group(0).count("\n")  # noqa: E731
    if kind in ("css", "html", "js"):
        text = re.sub(r"/\*.*?\*/", keep_nl, text, flags=re.S)
    if kind == "html":
        text = re.sub(r"<!--.*?-->", keep_nl, text, flags=re.S)
    if kind in ("js", "html"):
        text = re.sub(r"(?<![:\"'\\])//[^\n]*", "", text)
    return text


def line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def defined_css_vars() -> set:
    names = set()
    for p in [CSS_FILE, *WEB.glob("*.html"), *(WEB / "static" / "js").glob("*.js")]:
        if p.exists():
            t = read(p)
            names.update(CSS_VAR_DEF_RE.findall(t))
            names.update(CSS_VAR_SET_RE.findall(t))
    return names


def check_web_file(p: Path, css_vars: set) -> list:
    errs = []
    raw = read(p)
    kind = p.suffix.lstrip(".")
    text = strip_comments(raw, kind)
    name = rel(p)

    if kind == "html":
        checker = _TagChecker()
        checker.feed(raw)
        checker.close()
        errs += [f"{name}: {e}" for e in checker.errors]
        errs += [f"{name}: <{t}> (line {ln}) 닫히지 않음" for t, ln in checker.stack]
        for id_, lines in checker.ids.items():
            if len(lines) > 1:
                errs.append(f"{name}: id 중복 '{id_}' (lines {lines})")
        for m in FRAMEWORK_SRC_RE.finditer(text):
            errs.append(f"{name}:{line_of(text, m.start())}: 프론트 프레임워크 로드 금지 ({m.group(1)})")

    for m in EMOJI_RE.finditer(text):
        errs.append(f"{name}:{line_of(text, m.start())}: 이모지 금지 (SVG 아이콘 사용)")
    for m in GRADIENT_RE.finditer(text):
        errs.append(f"{name}:{line_of(text, m.start())}: 그라데이션 금지 (플랫 디자인)")
    for m in KOREAN_WEEK_RE.finditer(text):
        errs.append(f"{name}:{line_of(text, m.start())}: 한글 주차 표기 금지 ('{m.group(0)}' -> Jun-W3 형식)")
    for m in CSS_VAR_USE_RE.finditer(text):
        var, closer = m.group(1), m.group(2)
        if closer == ")" and var not in css_vars:
            errs.append(f"{name}:{line_of(text, m.start())}: 정의되지 않은 CSS 변수 {var}")
    return errs


def check_py_file(p: Path) -> list:
    errs = []
    text = read(p)
    for m in FORBIDDEN_PY.finditer(text):
        errs.append(f"{rel(p)}:{line_of(text, m.start())}: ML 라이브러리 금지 ({m.group(1)})")
    return errs


def check_requirements() -> list:
    errs = []
    for p in ROOT.glob("requirements*.txt"):
        for m in FORBIDDEN_REQ.finditer(read(p)):
            errs.append(f"{rel(p)}: ML 라이브러리 의존성 금지 ({m.group(1)})")
    return errs


def venv_python() -> str:
    for cand in (ROOT / "venv" / "Scripts" / "python.exe", ROOT / "venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


def run_tool(args: list, label: str) -> list:
    try:
        proc = subprocess.run(
            [venv_python(), "-m", *args], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=600,
        )
    except subprocess.TimeoutExpired:
        return [f"{label}: 시간 초과"]
    if proc.returncode == 0:
        return []
    out = (proc.stdout + proc.stderr).strip()
    if "No module named" in out:
        return [f"{label}: 개발 의존성 없음 -> venv python -m pip install -r requirements-dev.txt"]
    return [f"{label} 실패:\n{out[-3000:]}"]


def collect_targets(files):
    web_files, py_files = [], []
    if files:
        for f in files:
            p = (ROOT / f).resolve() if not Path(f).is_absolute() else Path(f).resolve()
            if not p.exists() or ROOT not in p.parents:
                continue
            if p.suffix in (".html", ".css", ".js") and WEB in p.parents:
                web_files.append(p)
            elif p.suffix == ".py" and "venv" not in p.parts:
                py_files.append(p)
    else:
        web_files = [*WEB.glob("*.html"), CSS_FILE, *(WEB / "static" / "js").glob("*.js")]
        py_files = [p for d in ("app", "tests", "scripts") for p in (ROOT / d).rglob("*.py")]
        py_files.append(ROOT / "seed_data.py")
    return web_files, py_files


def baseline_key(err: str) -> str:
    """줄 번호를 지워 코드가 밀려도 같은 결함으로 인식한다."""
    err = re.sub(r":\d+:", ":", err)
    return re.sub(r"\s*\((?:line|lines) [^)]*\)", "", err).strip()


def load_baseline() -> set:
    if not BASELINE.exists():
        return set()
    lines = read(BASELINE).splitlines()
    return {ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", help="검사할 파일 (생략 시 전체)")
    ap.add_argument("--tests", action="store_true", help="ruff + pytest 포함")
    ap.add_argument("--write-baseline", action="store_true", help="현재 정적 결함을 baseline으로 저장")
    args = ap.parse_args()

    web_files, py_files = collect_targets(args.files)
    css_vars = defined_css_vars()
    errors = []
    for p in web_files:
        errors += check_web_file(p, css_vars)
    for p in py_files:
        errors += check_py_file(p)
    if not args.files:
        errors += check_requirements()

    if args.write_baseline:
        keys = sorted({baseline_key(e) for e in errors})
        header = "# verify.py 기존 결함 목록. 새 항목 추가는 사용자 승인 필요. 고친 항목은 삭제.\n"
        BASELINE.parent.mkdir(exist_ok=True)
        BASELINE.write_text(header + "\n".join(keys) + "\n", encoding="utf-8")
        print(f"[verify] baseline {len(keys)}건 저장: {rel(BASELINE)}")
        return 0

    baseline = load_baseline()
    known = [e for e in errors if baseline_key(e) in baseline]
    errors = [e for e in errors if baseline_key(e) not in baseline]
    if not args.files:
        found = {baseline_key(e) for e in known}
        fixed = sorted(baseline - found)
        if fixed:
            print(f"[verify] 해결된 기존 결함 {len(fixed)}건 -> baseline에서 삭제:")
            for f in fixed:
                print(f"  {f}")

    if py_files and (args.tests or args.files):
        errors += run_tool(["ruff", "check", "--quiet", *[rel(p) for p in py_files]], "ruff")
    if args.tests:
        errors += run_tool(["pytest", "-x", "-q", "--no-header", "-p", "no:cacheprovider"], "pytest")

    if errors:
        print(f"[verify] 실패 {len(errors)}건")
        for e in errors:
            print(f"- {e}")
        return 1
    note = f" (기존 결함 {len(known)}건 제외)" if known else ""
    print(f"[verify] 통과{note}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
