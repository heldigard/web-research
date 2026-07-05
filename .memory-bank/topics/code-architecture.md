# Code Architecture — web-research

> Package map + data flow. Refresh after major refactors.
> Last update: 2026-07-05 (post architecture refactor).

## Package layout (src/web_research/)

```
__init__.py          public re-exports + module aliases (wr.search/reader/synthesis)
__main__.py          python -m web_research
cli.py               main(): build_parser + dispatch (~28 LOC)
cli_parser.py        build_parser(handlers) — handlers injected (no circular import)

shared/              generic typed infra; NEVER imports from features
  config.py          Settings dataclass + env loader + legacy SCREAMING_CASE proxy
  http.py            HttpClient Protocol + UrllibHttpClient + default_client()/swap
  cache.py           schema-versioned on-disk cache (entry stamped w/ SCHEMA_VERSION)
  ollama_api.py      generate/is_alive/embed/cosine (wraps shared ollama_client)
  formatters.py      fmt_results/fmt_smart_results
  cli_helpers.py     apply_common (--timeout/--verbose → settings.reload)
  results.py         strip_internal/snippets_to_docs (pure dict transforms)
  compat.py          optional harness import bootstrap (ollama_client, cheap_llm)

features/            one responsibility per folder (vertical slice)
  search/
    command.py             mode_search
    engine.py              thin dispatcher: fan-out, dedup, dict projection
    backends/
      __init__.py          BUILTIN_BACKENDS registry + build_backend factory
      base.py              SearchResult dataclass + URL canonicalization
      searxng.py           SearXNGBackend (GET /search?format=json, zero auth)
      minimax.py           MinimaxBackend (POST minimax_url, Bearer auth)
      zai.py               ZaiBackend (POST zai_search_url, recency filter)
  read/
    command.py             mode_read
    engine.py              thin dispatcher with fallback chain
    backends/
      __init__.py          BUILTIN_READERS registry + build_reader factory
      base.py              Page dataclass + tracking helpers
      firecrawl.py         FirecrawlReader (POST /v1/scrape, Bearer auth)
      zai_reader.py        ZaiReader (POST zai_reader_url, Bearer auth)
  research/command.py      orchestrate search → scrape → synth (multi-step pipeline)
  ranking/engine.py        rerank_results, source_quality_score, annotate_quality
  intelligence/engine.py   query_profile, expand_queries, focused_extract
  synthesis/engine.py      synthesize, _render_structured; cheap_llm fallback
```

## Data flow

### search
`mode_search` → (cache?) → `search_backends` (dispatch: SearXNG/MiniMax/Z.AI +
SearXNG fallback + URL canonical dedup) → optional `annotate_quality` +
`rerank_results` (Ollama embed) → `fmt_results` OR (--smart) `query_profile` +
`synthesize(structured)` + `fmt_smart_results`.

### read
`mode_read` → (cache?) → `read_with_fallback` (engine: requested →
firecrawl → zai if keyed) → truncate to `--max-chars` → print.

### research (orchestrator)
`mode_research` → `query_profile` (recency?) → `_search_phase` (cache or
`search_backends`) → `annotate_quality` + (if Ollama alive) `rerank_results` →
`ThreadPoolExecutor` over `scrape_with_fallback` → `_build_docs` (optional
`focused_extract` when --smart) → `synthesize` (answer_mode/structured) →
answer + sources footer, OR fallback full-doc dump.

## Coupling rules
- `shared/` → may import stdlib + each other (siblings). NEVER `features/`.
- `features/<x>/engine.py` → may import `shared/` + sibling `features/<y>/engine.py`.
- `features/<x>/command.py` → orchestrator; imports engines + shared freely.
- `features/<x>/backends/<name>.py` → may import `shared/`; never reaches
  cross-backend. Each backend reads its own URL/key from `get_settings()`.
- Each backend depends on `HttpClient` via `default_client()` — swappable.
- Engine modules are READ by their feature `command.py` + re-exported in `__init__.py`.

## Test contract
- Network fully mocked (`urllib.request.urlopen`, `ollama_client.*`,
  `default_client()` via fake injection).
- `patch.object(wr.search, "MINIMAX_API_KEY")` retargeted to the per-backend
  module after the 2026-07-05 split: `wr.search.backends.minimax` / `.zai`.
- Legacy SCREAMING_CASE config reads (`config.TIMEOUT`) work via the
  proxy; module-level writes (`config.TIMEOUT = 90`) go to module
  `__dict__` — they stale-cache. `reload_settings()` clears the cache.
- `pyproject.toml` `[tool.pytest.ini_options] pythonpath = ["src"]`.

## Adding a new search backend (recipe)
1. Write `features/search/backends/<name>.py` with a class:
   ```python
   class MyBackend:
       name = "my"
       def __init__(self, api_key=None, base_url=None) -> None: ...
       def search(self, query: str, num: int, **opts) -> list[SearchResult]: ...
   ```
2. Register one line: `BUILTIN_BACKENDS["my"] = MyBackend` in
   `features/search/backends/__init__.py`.
3. The CLI's `--engine my` plumbs through to `engine="my"` →
   `build_backend("my")()` automatically. Tests can
   `patch.object(wr.search.backends.<name>, "API_KEY", "sk-test")`.

## Adding a new reader (recipe)
Same pattern under `features/read/backends/`. `read(url, **opts) -> str`.

## Swapping the HTTP transport
```python
# shared/http_httpx.py
class HttpxClient:
    def get_json(self, url, *, timeout=None, headers=None): ...
    def post_json(self, url, payload, *, timeout=None, headers=None): ...
    def get_bytes(self, url, *, timeout=None, headers=None): ...

# at startup / from a config flag
from web_research.shared.http import set_default_client
set_default_client(HttpxClient())
```
No edits to backends or the dispatcher.
