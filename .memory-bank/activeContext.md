# Active Context
- 2026-07-08: cross-CLI ecosystem improvements SHIPPED (P4 + P1 phase-1).

## Current Objective
- **Task**: improve the cross-CLI ecosystem (web-research ↔ graduated projects).
  User authorized autonomous ("procede, eres autonomo").
- **Acceptance**: ship concrete ecosystem improvements with zero breakage to
  existing consumers.
- **Status**: DONE — P4 + P1 phase-1 shipped, 108 tests green, ruff+mypy clean.

## Verified (this session)
- **P4** (`research --code-analyze`, commit 4295b68): codeq fusion module
  `features/intelligence/code_analyze.py`; identifier-like query tokens resolved
  in CWD via `codeq find`+`refs`; honest scope (local repo, not scraped text);
  graceful no-op when codeq absent/no hits. 13 tests; suite 108.
- **P1 phase-1**: `ollama_client` graduated to `~/ollama-client/` (SemVer 1.0.0,
  `require()`, pyproject, flat module mirroring cheap-llm);
  `~/.claude/scripts/ollama_client.py` → re-export shim (verified: loads
  graduated module, full API + CLI delegation intact);
  `web-research/shared/compat.py` version-gates `oc.require('1.0')` (0942350).
- Zero breakage: shim preserves the import contract for all 4 consumers
  (codeq/smart-trim/prompt-improve untouched).

## Next likely work
- **Await user ok** to (a) push `~/ollama-client/` to github.com/heldigard/
  ollama-client, and (b) merge `feat/ollama-client-graduation` into ~/.claude
  main. Until then both stay local/branched.
- **P1 phase-2** (optional): migrate codeq/smart-trim/prompt-improve off the
  shim to the real `ollama_client` package + `require()`. Incremental.
- **P2** (model registry), **P3** (shared LLM cache, post-P1), **P5**
  (unified harness_path) — deferred per scope.

## Files touched this session
- `src/web_research/features/intelligence/code_analyze.py` (new)
- `src/web_research/features/research/command.py`, `src/web_research/cli_parser.py`
- `tests/test_enhancements.py`, `CHANGELOG.md`, `.memory-bank/REFERENCE.md`
- `src/web_research/shared/compat.py`
- `~/ollama-client/` (new graduated project), `~/.claude/scripts/ollama_client.py` (shim)
