# CONTEXT - Current State
> Updated: 2026-07-04 (graduation day)

## What this project is
The `web_research` engine extracted from `~/.claude/scripts/web_research/`
(flat 13-module package, 1302 LOC) into a standalone vertical-slice project at
`~/web-research/`. Mirrors the `codeq` / `smart-trim` / `prompt-improve`
graduation pattern.

## Active Focus
SHIPPED. Repo created public at github.com/heldigard/web-research. Ecosystem
reconnected via the shim at `~/.claude/scripts/web-research.py`. All 37 tests
green, ruff clean, harness self-tests pass.

## Recent Changes (2026-07-04)
- Restructured flat modules into `features/{search,read,research,ranking,intelligence,synthesis}/` + `shared/`.
- Extracted the 3 mode-handlers from the 255-LOC `cli.py` into per-feature `command.py`; slimmed `cli.py` to ~28 LOC dispatch.
- Fixed the cheap_llm/ollama_client coupling: the old `SCRIPT_DIR = parent.parent` trick broke on move → replaced with `ECOSYSTEM_SCRIPTS` env (default `~/.claude/scripts`), graceful degrade preserved.
- Rewrote `~/.claude/scripts/web-research.py` shim → `WEB_RESEARCH_HOME`-based, imports from `~/web-research/src/`.
- Added `~/.local/bin/web-research` symlink. Removed the old flat package + old test (committed in `~/.claude` as 4bcbc80).

## Key decision: cheap_llm + ollama_client STAY in ~/.claude/scripts/
They are shared infrastructure used by 8+ other tools (commit-draft, pr-draft,
diff-review, test-triage, error-classify, pdf-extract-structured, intent_route,
extract-tool-output). This engine loads them OPTIONALLY via `ECOSYSTEM_SCRIPTS`
and degrades gracefully (try/except → None) when absent. cheap_llm is a future
graduation candidate on its own, but out of scope here.

## Blockers / Risks
- None current. Live verification (steps 2-4 of the plan) depends on SearXNG
  `:8080`, Firecrawl `:3002`, Ollama `:11434` being up; unit tests are network-mocked.

## Next Steps
- Update the HOME memory bank (`~/.memory-bank/` or `~/.claude/projects/.../memory/`)
  with a graduation pointer entry (matches how codeq/smart-trim graduations were recorded).
- cheap_llm graduation is a separate future project if it grows further.
