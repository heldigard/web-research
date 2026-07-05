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
- 2026-07-05T19:25:55Z | 2026-07-05: Improved web-research smart flow for cross-CLI LLM agents. Smart search/research now builds a bounded query set from query_profile expansions + preferred site filters; search_backends accepts optional internal query variants while keeping the public result contract and canonical URL dedup removes fragments/tracking params. Synthesis now enforces WEB_SYNTH_MAX_CONTEXT_CHARS (default 14000) and truncates source text before local/cloud model calls to reduce token spend without changing read/search output. Verified pytest -q (56 passed) and ruff check .; codescan all reported 0 leaks then failed in its own SAST wrapper (Namespace.config missing).
- 2026-07-05T20:00:48Z | 2026-07-05: Added canonical shims/web-research.py plus tests/test_shim.py and restored live ~/.claude/scripts/web-research.py + no-suffix web-research entrypoints. Isolated-HOME E2E and pytest+ruff passed.
- 2026-07-05T22:30:00Z | status:completed | session:e2ab894 | Architecture refactor SHIPPED. (1) chore(ci) e2ab894: added ruff format check + mypy strict + 85% coverage gate to .github/workflows/ci.yml; annotated one pre-existing sections: list[str] mypy error in synthesis/engine. (2) refactor(shared) 5e2fb2d: shared/config.py → frozen Settings dataclass + env loader + legacy SCREAMING_CASE proxy + get_settings/reload_settings API; externalized MINIMAX_URL, ZAI_SEARCH_URL, ZAI_READER_URL. shared/http.py → HttpClient Protocol + UrllibHttpClient default + default_client()/set_default_client() swap (future httpx is one setter call) + nosemgrep rationale on urlopen. shared/cache.py → schema-versioned entries (SCHEMA_VERSION + optional engine_tag), auto-invalidates on model/prompt change. (3) refactor(search) a4eae5b: features/search/engine.py → thin dispatcher; new features/search/backends/{base,searxng,minimax,zai}.py package (one file per backend, ~65-95 LOC). (4) refactor(read) cea2e49: features/read/engine.py → thin dispatcher with fallback chain; new features/read/backends/{base,firecrawl,zai_reader}.py. (5) test 26f964a: 3 legacy patches retargeted to wr.search.backends.{minimax,zai} + new BackendSliceTests class asserting build_backend/normalize_url/SearchResult.to_dict/Settings reload/cache invalidation without HTTP. (6) docs 68941e3: ARCHITECTURE.md describing vertical-slice layout + 3-step recipes for new backends + HttpClient swap procedure + schema-version cache contract. Verified: ruff format+lint clean, mypy clean, pytest 63/63 pass, coverage 89% (gate 85%), codescan dead=0, codescan secrets=0, live SearXNG smoke returns real Rust-2026 results.
