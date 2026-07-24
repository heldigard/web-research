# Reference — stable facts

## CLI (src/web_research/cli.py → build_parser in cli_parser.py)

```
web-research search  <query> [-n 8] [--engine searxng|zai|minimax|duckduckgo]
                             [--cat general] [--lang en] [--time day|week|month|year]
                             [--rerank] [--smart] [--summary] [--json]
web-research read    <url>   [--engine firecrawl|zai|html] [--no-robots]
                             [--wait N] [--zai-timeout N] [--max-chars N]
web-research research <query> [-n 6] [--scrape 3] [--engine searxng|zai|minimax|duckduckgo]
                             [--time ...] [--answer] [--smart] [--max-chars N] [--no-robots]
                             [--code-analyze] [--json]
web-research status [--json]   # probe local services + models/keys/cache
web-research capabilities      # machine-readable router contract; no network probes

Common: --no-cache --timeout N --verbose
```

## `--code-analyze` (research only)
Opt-in fusion with local code intelligence (`features/intelligence/code_analyze.py`).
Identifier-like tokens from the query are resolved in the CWD via the `codeq`
CLI (`find` + `refs`); hits append a `## Local code context (codeq)` section to
each scraped doc before synthesis. No-op when `codeq` is absent or no symbol
resolves locally. Honest scope: `codeq` sees the local repo, not scraped text —
the value is weaving web findings with how the symbol is used in the caller's
own code.

## Entry points (4 equivalent ways in)
- Wired ecosystem shim: `~/.claude/scripts/web-research.py` (skills call this)
- PATH symlink: `~/.local/bin/web-research` → the shim
- Console script (`pip install -e .`): `web-research`
- Local dev: `python3 shim.py <cmd>` (inserts `src/` onto sys.path)

## External services (must be up for live calls)
| Service  | Default URL              | Env override  |
|----------|--------------------------|---------------|
| SearXNG  | http://localhost:8080    | `SEARXNG_URL` |
| Firecrawl| http://localhost:3002    | `FC_URL` + `FC_API_KEY` |
| Ollama   | http://localhost:11434   | `OLLAMA_URL` |
| TEI rerank (optional) | (unset = disabled) | `TEI_RERANK_URL` |

## Backend API endpoints (externalized 2026-07-05)
| Service  | Default URL                                          | Env override     |
|----------|------------------------------------------------------|------------------|
| MiniMax  | https://api.minimax.io/v1/coding_plan/search         | `MINIMAX_URL`    |
| Z.AI search | https://api.z.ai/api/paas/v4/web_search           | `ZAI_SEARCH_URL` |
| Z.AI reader | https://api.z.ai/api/paas/v4/reader               | `ZAI_READER_URL` |
| DuckDuckGo | https://html.duckduckgo.com/html/ (no key)        | —                |
| TEI rerank | `{TEI_RERANK_URL}/rerank` (POST, optional)        | `TEI_RERANK_URL` |

## Model routing
- `OLLAMA_MODEL` (default `cryptidbleh/gemma4-claude-opus-4.6`) — query_profile, focused_extract.
- `OLLAMA_SYNTH_MODEL` (default `hf.co/TeichAI/Qwen3.5-9B-Fable-5-v1-GGUF:Q4_K_M`) — final cited synthesis.
- `OLLAMA_EMBED` (default `embeddinggemma`) — rerank embeddings (MRR 0.724).
- `WEB_SYNTH_CLOUD_MODEL` (default `deepseek/deepseek-v4-flash`) — cloud fallback.
- API keys: `ZAI_API_KEY` / `Z_AI_API_KEY`, `MINIMAX_API_KEY`.
- `WEB_RESEARCH_TIMEOUT` (default 30s) — HTTP timeout override.
- HTTP retry (2026-07-08): `WEB_RESEARCH_HTTP_RETRIES` (default 2),
  `WEB_RESEARCH_HTTP_BACKOFF` (default 0.2s). 429/5xx/URLError retried;
  other 4xx surfaces immediately.

## Sibling ecosystem scripts (NOT in this repo)
- `WEB_RESEARCH_SCRIPTS` (default `~/.claude/scripts/`) →
  location of `ollama_client.py` (embed/generate/is_alive, used by
  ranking/intelligence/synthesis) and `cheap_llm.py` (cloud cascade,
  synthesis fallback). Both optional; graceful degrade when absent.
- `CHEAP_LLM_HOME` is consumed inside the `cheap_llm.py` shim only; it does
  not replace the shared scripts directory.

## Cache
On-disk JSON cache at `WEB_RESEARCH_CACHE_DIR` (default
`~/.cache/web-research/`), TTL `WEB_RESEARCH_CACHE_TTL` (default 3600s).
Bypass with `--no-cache`.

**Size-bound LRU eviction (corrected 2026-07-12):** every successful `set()`
sweeps least-recently-used entries by mtime when
`WEB_RESEARCH_CACHE_MAX_ENTRIES` (default 500; `0` = no limit) or
`WEB_RESEARCH_CACHE_MAX_BYTES` (default 50 MB; `0` = no limit) is exceeded.
Each axis is independent. Valid `get()` calls promote mtime but TTL continues
to use the serialized `ts`. Failed writes do not trigger eviction.

Search cache keys distinguish reranked/unranked artifacts. Read cache keys
distinguish robots policy and `zai_timeout`; content fetched with
`--no-robots` cannot satisfy a later robots-respecting read.

## Capability manifest options (2026-07-12)
`web-research capabilities` retains schema version 1 and all original fields,
with additive per-command `options` metadata for engines, cache/timeout/
verbose controls, robots policy, reader limits, structured output, and
`research --code-analyze` (`dependency=codeq`, unavailable=`no_op`).

**Schema-versioned (2026-07-05):** every entry is stamped with
`SCHEMA_VERSION` (= 1) and an optional caller-supplied `engine_tag`.
Entries stamped with a prior schema are deleted on read and treated as
miss. Pass `engine_tag=OLLAMA_SYNTH_MODEL` from the synthesis call so
changing the model invalidates the prior synthesis cache automatically.

## Architecture layers (2026-07-05 refactor)

```
src/web_research/
├── cli.py + cli_parser.py       entrypoint + argparse (handlers injected)
└── shared/                      typed infra; never imports features
    ├── config.py                Settings dataclass + env + legacy proxy
    ├── http.py                  HttpClient Protocol + UrllibHttpClient (retry/backoff)
    ├── cache.py                 schema-versioned on-disk cache + LRU eviction
    ├── robots.py                robots.txt gate (stdlib, fail-open) [2026-07-08]
    └── ollama_api.py / formatters.py / results.py / ...

features/                        one responsibility per slice
    search/
      command.py                 mode_search
      engine.py                  thin dispatcher
      backends/{base,searxng,minimax,zai,duckduckgo}.py
    read/
      command.py                 mode_read (unified onto read_with_fallback)
      engine.py                  thin dispatcher + fallback chain (→ html last)
      backends/{base,firecrawl,zai_reader,html}.py
    research/command.py          orchestrator (--no-robots wired via partial)
    ranking/
      engine.py                  rerank + source-quality (stopword-aware overlap)
      tei_rerank.py              optional TEI cross-encoder stage-2 [2026-07-08]
      data/authority_domains.txt packaged authority list [2026-07-08]
    intelligence/engine.py       query profile + expand + focused extract
    synthesis/engine.py          cited synthesis + tolerant JSON extractor
```

Adding a new backend = one file under `backends/<name>.py` + one entry in
`BUILTIN_BACKENDS` / `BUILTIN_READERS`. Dispatcher never changes.

## Commands
- Install (dev): `uv sync --extra test` (editable install)
- Test: `uv run python -m pytest tests/ -q` (186 tests, network mocked) ·
  `--cov=web_research --cov-fail-under=85`
- Lint: `uv run ruff check src tests` · Format: `uv run ruff format --check .`
- Types: `uv run mypy src/`
- Smoke: `python3 shim.py search "test" -n 2`
