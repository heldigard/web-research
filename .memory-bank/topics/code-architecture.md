# Code Architecture — web-research

> Package map + data flow. Refresh after major refactors.

## Package layout (src/web_research/)

```
__init__.py          public re-exports + module aliases (wr.search/reader/synthesis)
__main__.py          python -m web_research
cli.py               main(): build_parser + dispatch (~28 LOC)
cli_parser.py        build_parser(handlers) — handlers injected (no circular import)

shared/              generic infra; NEVER imports from features
  config.py          env-derived config + ECOSYSTEM_SCRIPTS path
  http.py            _get_json/_post_json/_encode_query/_debug/_warn
  ollama_api.py      generate/is_alive/embed/cosine (wraps shared ollama_client)
  cache.py           on-disk JSON cache get/set
  formatters.py      fmt_results/fmt_smart_results
  cli_helpers.py     apply_common (--timeout/--verbose → config)
  results.py         strip_internal/snippets_to_docs (pure dict transforms)

features/            one responsibility per folder
  search/    command.py (mode_search) + engine.py (searxng/zai/minimax/search_backends)
  read/      command.py (mode_read)   + engine.py (firecrawl/zai_reader/scrape_with_fallback)
  research/  command.py (mode_research — orchestrator)
  ranking/   engine.py (rerank_results, source_quality_score, annotate_quality)
  intelligence/ engine.py (query_profile, expand_queries, focused_extract)
  synthesis/ engine.py (synthesize, _render_structured; cheap_llm fallback)
```

## Data flow

### search
`mode_search` → (cache?) → `search_backends` (SearXNG/ZAI/MiniMax dispatch +
dedup) → optional `annotate_quality` + `rerank_results` (Ollama embed) →
`fmt_results` OR (smart) `query_profile` + `synthesize(structured)` +
`fmt_smart_results`.

### read
`mode_read` → (cache?) → `_fetch_markdown` (engine order: requested → Firecrawl
→ Z.AI if key) → truncate to `--max-chars` → print.

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
- Engine modules are READ by their feature `command.py` + re-exported in `__init__.py`.

## Test contract
- `patch.object(wr.search, "MINIMAX_API_KEY")` works because `__init__.py`
  aliases `wr.search` → `features.search.engine` (the module where the name binds).
- Network fully mocked (`urllib.request.urlopen`, `ollama_client.*`).
