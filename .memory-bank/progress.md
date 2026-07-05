# Progress

## 2026-07-04 — Graduation milestone (SHIPPED)
- Scaffolded `~/web-research/` (pyproject, .gitignore, shim.py, LICENSE, CLAUDE.md, README.md). ✅
- Copied flat package verbatim into `src/web_research/` + migrated test suite. ✅
- Added `ECOSYSTEM_SCRIPTS` to `shared/config.py`; fixed `ollama_api.py` + `synthesis/engine.py` path injection (replaced broken `parent.parent` trick). ✅
- Baseline green (37 tests) against the new location. ✅
- Restructured into vertical slices: `features/{search,read,research,ranking,intelligence,synthesis}/` + `shared/`. ✅
- Extracted 3 mode-handlers from `cli.py` (255 LOC) into per-feature `command.py`; slimmed `cli.py` to ~28 LOC. ✅
- Added module aliases (`wr.search`/`wr.reader`/`wr.synthesis`) in `__init__.py` for test-compat; updated 3 test import paths. ✅
- All 37 tests green against the NEW package (resolved the stale `~/.claude/scripts` sys.path block that was shadowing the new package in the baseline — corrected). ✅
- ruff check + format clean (29 files). ✅
- Rewrote `~/.claude/scripts/web-research.py` shim → `WEB_RESEARCH_HOME`-based (mirrors codeq). ✅
- Added `~/.local/bin/web-research` symlink. ✅
- Removed old flat package + old test; committed in `~/.claude` as `4bcbc80`. ✅
- harness self-tests pass: verify-hooks 0 errors, test-rtk-config 71/71. ✅
- Init + seeded this memory bank. ✅
- Created github.com/heldigard/web-research (public), pushed. ✅

## Format
- [YYYY-MM-DD]: What was done + verification status
- 2026-07-05T02:12:16Z | status:completed | session:97300642-77bb-4a6e-981c-8ef060ef7e95 | claude: session done
