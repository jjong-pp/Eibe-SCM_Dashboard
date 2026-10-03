"""역할·스킬 원본(.agents/)에서 Claude Code·Codex 설정 파일을 생성한다.

  python scripts/sync_agents.py          # 생성
  python scripts/sync_agents.py --check  # 생성물이 원본과 다르면 exit 1

원본                              생성물
.agents/roles/<name>.toml    ->  .claude/agents/<name>.md, .codex/agents/<name>.toml
.agents/skills/<x>/          ->  .claude/skills/<x>/          (*-rules 제외)
.agents/skills/<x>-rules/    ->  .claude/rules/<x>.md         (paths 조건부 로드)
Codex는 .agents/skills/를 직접 읽으므로 복사하지 않는다.
"""

import argparse
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / ".agents" / "roles"
SKILLS = ROOT / ".agents" / "skills"
CLAUDE = ROOT / ".claude"
CODEX = ROOT / ".codex"

# Claude 경로 조건부 룰: 해당 파일을 다룰 때만 컨텍스트에 로드된다
RULE_PATHS = {
    "frontend-rules": ["web/**"],
    "backend-rules": ["app/routers/**", "app/core/**", "app/schemas.py", "app/main.py", "tests/**"],
    "data-rules": ["app/models.py", "app/database.py", "app/core/snapshot.py", "seed_data.py",
                   "migrations/**", "start_server.bat"],
}
HEADER = "생성 파일. 원본 {src} 수정 후 python scripts/sync_agents.py 실행"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def yaml_value(value, indent: int = 0) -> str:
    pad = " " * indent
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        if all(isinstance(v, str) for v in value):
            return "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in value) + "]"
        return "\n" + "\n".join(f"{pad}- {yaml_value(v, indent + 2).lstrip()}" for v in value)
    if isinstance(value, dict):
        return "\n" + "\n".join(f"{pad}{k}: {yaml_value(v, indent + 2)}" for k, v in value.items())
    raise TypeError(value)


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip("\n")
    return text


def build() -> dict:
    """생성할 파일 {경로: 내용}."""
    out = {}
    for role_file in sorted(ROLES.glob("*.toml")):
        role = tomllib.loads(role_file.read_text(encoding="utf-8"))
        name, desc = role["name"], role["description"]
        body = role["body"]["instructions"].strip()
        src = f".agents/roles/{role_file.name}"

        # Claude subagent
        fm = {"name": name, "description": desc}
        claude = dict(role.get("claude", {}))
        mcp = claude.pop("mcpServers", None)
        fm.update(claude)
        lines = ["---"] + [f"{k}: {yaml_value(v, 2)}" for k, v in fm.items()]
        if mcp:
            lines.append("mcpServers:")
            for server, conf in mcp.items():
                lines.append(f"  - {server}:")
                lines += [f"      {k}: {yaml_value(v, 8)}" for k, v in conf.items()]
        lines += ["---", "", f"<!-- {HEADER.format(src=src)} -->", "", body, ""]
        out[CLAUDE / "agents" / f"{name}.md"] = "\n".join(lines)

        # Codex custom agent
        codex = dict(role.get("codex", {}))
        read_first = codex.pop("read_first", [])
        instr = body
        if read_first:
            instr += "\n\n## 시작 전에 읽을 파일\n" + "\n".join(f"- {p}" for p in read_first)
        assert "'''" not in instr, f"{src}: instructions에 ''' 사용 불가"
        toml = [f"# {HEADER.format(src=src)}",
                f"name = {json.dumps(name, ensure_ascii=False)}",
                f"description = {json.dumps(desc, ensure_ascii=False)}"]
        toml += [f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in codex.items()]
        toml += ["developer_instructions = '''", instr, "'''", ""]
        out[CODEX / "agents" / f"{name}.toml"] = "\n".join(toml)

    for skill_dir in sorted(p for p in SKILLS.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        if skill_dir.name in RULE_PATHS:
            area = skill_dir.name.removesuffix("-rules")
            paths = "\n".join(f'  - "{p}"' for p in RULE_PATHS[skill_dir.name])
            body = strip_frontmatter(skill_md.read_text(encoding="utf-8"))
            src = f".agents/skills/{skill_dir.name}/SKILL.md"
            out[CLAUDE / "rules" / f"{area}.md"] = (
                f"---\npaths:\n{paths}\n---\n\n<!-- {HEADER.format(src=src)} -->\n\n{body}")
            continue
        for f in sorted(skill_dir.rglob("*")):
            if f.is_file():
                out[CLAUDE / "skills" / skill_dir.name / f.relative_to(skill_dir)] = f.read_text(encoding="utf-8")
    return out


def stale_files(expected: dict) -> list:
    """원본에서 사라진 생성물 (자동 생성 디렉터리 안에서만)."""
    managed = set(expected)
    stale = []
    for d in (CLAUDE / "agents", CODEX / "agents", CLAUDE / "skills", CLAUDE / "rules"):
        if d.exists():
            stale += [p for p in d.rglob("*") if p.is_file() and p not in managed]
    return stale


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    expected = build()
    diff = [p for p, text in expected.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
    stale = stale_files(expected)
    if args.check:
        for p in diff + stale:
            print(f"동기화 필요: {p.relative_to(ROOT).as_posix()}")
        return 1 if diff or stale else 0
    for p in diff:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(expected[p], encoding="utf-8", newline="\n")
    for p in stale:
        p.unlink()
    print(f"생성 {len(diff)}개, 삭제 {len(stale)}개, 전체 {len(expected)}개 관리 중")
    return 0


if __name__ == "__main__":
    sys.exit(main())
