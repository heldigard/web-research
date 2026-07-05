# System Patterns

## Layout: vertical-slice CLI package
```
src/web_research/
  cli.py              thin wiring: build_parser + dispatch (~28 LOC)
  cli_parser.py       argparse construction (handlers injected → no circular import)
  __main__.py         python -m web_research
  shared/             config, http, ollama_api, cache, formatters, cli_helpers, results
                      (generic infra; NEVER imports from features — low coupling)
  features/
    search/    command.py (mode_search) + engine.py (searxng/zai/minimax/search_backends)
    read/      command.py (mode_read)   + engine.py (firecrawl/zai_reader/scrape_with_fallback)
    research/  command.py (mode_research — orchestrates search+rank+read+synth)
    ranking/   engine.py (rerank_results, source_quality_score, annotate_quality)
    intelligence/ engine.py (query_profile, expand_queries, focused_extract)
    synthesis/ engine.py (synthesize, _render_structured; cheap_llm fallback)
```

## Decisions

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
- 37 tests, network fully mocked (urllib + ollama_client patched).
- Tests migrated from `~/.claude/scripts/test_web_research.py`; the stale
  `sys.path.insert(0, "~/.claude/scripts")` block MUST stay removed (else pytest
  imports the old package — which no longer exists post-graduation).
- `pyproject.toml` `[tool.pytest.ini_options] pythonpath = ["src"]` resolves the
  package for tests.
