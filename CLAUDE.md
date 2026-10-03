@AGENTS.md

## Claude Code 전용
- 구현은 front·back·data 서브에이전트에 맡기고 메인 컨텍스트는 계획·판정·보고에 쓴다
- 넓은 검색은 explorer(또는 내장 Explore)에 맡기고 목록만 받는다
- 같은 작업 재시도는 새 서브에이전트 대신 SendMessage로 기존 에이전트를 재개한다
- review·police --judge는 `scripts/squad.py`가 Codex CLI로 실행한다 (교차 검증). Codex CLI를 못 찾으면 reviewer·police 서브에이전트로 대신하고 리포트에 same-family로 적는다
- 영역별 규칙은 `.claude/rules/`에서 해당 파일을 다룰 때 자동 로드된다
