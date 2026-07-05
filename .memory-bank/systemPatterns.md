# System Patterns

## Layout: vertical-slice CLI package (vertical-slices-honest, 2026-07-05)

```
src/web_research/
  cli.py              thin wiring: build_parser + dispatch (~28 LOC)
  cli_parser.py       argparse construction (handlers injected → no circular import)
  __main__.py         python -m web_research
  shared/             typed infra (Settings, HttpClient port, schema-version cache);
                      NEVER imports from features — low coupling
  features/
    search/    command.py + engine.py (thin dispatcher)
               backends/{base,searxng,minimax,zai}.py   ← 1 file per backend
    read/      command.py + engine.py (thin dispatcher + fallback chain)
               backends/{base,firecrawl,zai_reader}.py   ← 1 file per backend
    research/  command.py (orchestrator: search → scrape → synth)
    ranking/   engine.py (rerank_results, source_quality_score, annotate_quality)
    intelligence/ engine.py (query_profile, expand_queries, focused_extract)
    synthesis/ engine.py (synthesize, _render_structured; cheap_llm fallback)
```

Each backend is a class with a `name` + `search(query, num, **opts) -> list[SearchResult]`
(or `read(url, **opts) -> str` for readers). The dispatcher resolves
instances from a registry; backends depend on `HttpClient` via
`default_client()` so the HTTP transport is swappable in one place.

## Decisions

### [2026-07-05] HttpClient port — urllib default, httpx-ready
Backends historically reached into `urllib.request` directly through
`shared/http.py::_http` helpers. That made every backend a hard dep on
urllib and blocked retries / connection pooling. Refactored:
`HttpClient` Protocol (`get_json` / `post_json` / `get_bytes`) +
`UrllibHttpClient` default impl + `default_client()` /
`set_default_client(client)` swap. Backends resolve
`default_client()` at call time → future httpx swap is one
`set_default_client(HttpxClient())` call, no backend edits.
**Reason:** zero-cost BC + one swap point + easy test injection (a
`FakeHttpClient` for tests that don't want urllib patching).

### [2026-07-05] Per-backend file slices under `backends/<name>.py`
The 220-LOC `features/search/engine.py` collapsed 3 backends (SearXNG,
MiniMax, Z.AI) with different response shapes, auth models, and quirks
(recency, pagination) into one switch-on-field-names function. Same for
read. Restructured: one backend = one file under
`features/<slice>/backends/<name>.py` with a class implementing the
duck-typed contract. Registry in `__init__.py`. Dispatcher is thin
(fan-out + dedup + dict projection). **Reason:** cohesion > size —
each backend's quirks live in one place; adding a new backend is 1 file
+ 1 registry entry; the dispatcher never changes.

### [2026-07-05] Schema-versioned cache
On-disk JSON cache entries stamped with `SCHEMA_VERSION` (= 1, live in
`shared/config.py::SCHEMA_VERSION`). Bumping invalidates every prior
entry automatically on next read. Plus optional `engine_tag=` arg on
`cache.get/set` so callers pass `engine_tag=OLLAMA_SYNTH_MODEL` →
changing the synthesis model invalidates the synthesis cache without a
schema bump. **Reason:** changing models or prompt templates silently
served wrong answers before (cache hit → stale synthesis). Bumping is
cheap, readers do the work.

### [2026-07-05] Typed `Settings` dataclass + legacy SCREAMING_CASE proxy
Replaced module-level config globals with a frozen `@dataclass` loaded
from env via `load_settings()` / `get_settings()` / `reload_settings(**overrides)`.
Settings instance holds API URLs (`minimax_url`, `zai_search_url`,
`zai_reader_url`) so proxies / on-prem forks repoint via env without
code edits. A read-only `__getattr__` proxy maps legacy
`config.MINIMAX_API_KEY` → `settings.minimax_api_key` so existing tests
don't churn. `reload_settings()` ALSO clears any cached `__dict__`
entries on legacy names — necessary because Python does NOT invoke
module `__setattr__` for normal `module.x = y` assignments, so direct
test writes would stale-cache. **Reason:** type safety + BC + env
externalization in one change.

### [2026-07-05] CI quality gates (ruff format + mypy + coverage)
Added three missing gates to `.github/workflows/ci.yml`: `ruff format
--check` (was passing 3 unformatted files silently), `mypy src/`
(catches `object`/`str` mix-ups in legacy module proxy), and
`--cov=web_research --cov-fail-under=85` (was at 89% with no gate).
Annotated one pre-existing mypy error caught by the new gate
(`sections: list[str]` annotation in synthesis/engine). **Reason:**
silent drift on three axes was the highest-cost risk in the codebase.

### [2026-07-04] Vertical slices over flat modules
The flat package (search.py, reader.py, ranking.py, …) mixed concerns in
`cli.py` (255 LOC, 3 mode handlers — failed the one-sentence "and" test).
Restructured: one feature = one folder; `cli.py` split into per-mode
`command.py`. Engine modules kept COHESIVE (single ~60-175 LOC file per
feature, not over-split into 4 — cohesion > size per the vertical-slice rule).
**Reason:** user asked for "buena arquitectura de vertical slices"; matches
codeq/smart-trim layout; vertical-slice-guard enforces.

### [2026-07-04] Module aliases in __init__.py for test compat
Tests use `patch.object(wr.search, "MINIMAX_API_KEY")`, `wr.reader`, `wr.synthesis`
(module attribute access). After restructure, those modules live at
`features/<x>/engine.py`. `__init__.py` aliases them:
`from .features.search import engine as search` (etc.) so `wr.search` IS the
engine module where the patched name is bound. **Reason:** preserves the test
patch semantics with zero edits to the patch lines themselves. Only the
`from web_research.X import Y` and `import web_research.X` path forms needed
updates (cache → shared.cache, synthesis → features.synthesis.engine, etc.).

### [2026-07-04] ECOSYSTEM_SCRIPTS env replaces the parent.parent trick
The old flat package resolved sibling scripts (`ollama_client`, `cheap_llm`)
via `SCRIPT_DIR = Path(__file__).resolve().parent.parent` (= `~/.claude/scripts/`).
On move to `~/web-research/src/web_research/`, `parent.parent` = `~/web-research/src`
(wrong). Replaced with `ECOSYSTEM_SCRIPTS = os.getenv("WEB_RESEARCH_SCRIPTS",
"~/.claude/scripts")` in `shared/config.py`; `ollama_api.py` + `synthesis/engine.py`
inject it. **Reason:** one mechanism for both shared deps; configurable;
graceful degrade preserved (try/except → None). `cheap_llm` and `ollama_client`
stay shared in `~/.claude/scripts/` (8+ other consumers).

### [2026-07-04] Absolute imports, not relative, across the package
Feature engines use `from web_research.shared.X import` and
`from web_research.features.Y.engine import` (absolute). Shared modules keep
relative imports (`.config`, `.http`) because they're siblings within `shared/`.
**Reason:** absolute imports survive the nested feature layout without dot-count
errors; relative between siblings is fine and less churn.

### [2026-07-04] Shim-based ecosystem reconnection (zero skill edits)
All 11 web/search skills call `python3 ~/.claude/scripts/web-research.py <cmd>`.
Rewriting that shim to import from `~/web-research/src/` preserves the contract →
**zero skill edits**. Cross-CLI skill copies are symlinks to `~/.claude/skills/`
(managed by `sync-codex-skills.sh`) → no manual sync. Mirrors the `codeq` shim
pattern (`~/.claude/scripts/codeq`).

## Testing
- **63 tests** (was 37 at graduation), network fully mocked (urllib +
  ollama_client patched). Coverage **89%** (CI gate ≥85%).
- Tests migrated from `~/.claude/scripts/test_web_research.py`; the stale
  `sys.path.insert(0, "~/.claude/scripts")` block MUST stay removed (else pytest
  imports the old package — which no longer exists post-graduation).
- After 2026-07-05 backend split, three legacy `patch.object(wr.search, ...)`
  calls retargeted to `wr.search.backends.{minimax,zai}` (the per-backend
  module where the constant now lives).
- New `BackendSliceTests` class validates the new architecture end-to-end
  without HTTP (registry, dataclass shape, URL canonicalization,
  schema-version cache invalidation, typed-config reload roundtrip).
- `pyproject.toml` `[tool.pytest.ini_options] pythonpath = ["src"]` resolves the
  package for tests.
