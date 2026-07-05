# Reference — stable facts

## CLI (src/web_research/cli.py → build_parser in cli_parser.py)

```
web-research search  <query> [-n 8] [--engine searxng|zai|minimax]
                             [--cat general] [--lang en] [--time day|week|month|year]
                             [--rerank] [--smart] [--summary] [--json]
web-research read    <url>   [--engine firecrawl|zai] [--wait N] [--zai-timeout N]
                             [--max-chars N]
web-research research <query> [-n 6] [--scrape 3] [--engine ...] [--time ...]
                             [--answer] [--smart] [--max-chars N]

Common: --no-cache --timeout N --verbose
```

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

## Backend API endpoints (externalized 2026-07-05)
| Service  | Default URL                                          | Env override     |
|----------|------------------------------------------------------|------------------|
| MiniMax  | https://api.minimax.io/v1/coding_plan/search         | `MINIMAX_URL`    |
| Z.AI search | https://api.z.ai/api/paas/v4/web_search           | `ZAI_SEARCH_URL` |
| Z.AI reader | https://api.z.ai/api/paas/v4/reader               | `ZAI_READER_URL` |

## Model routing
- `OLLAMA_MODEL` (default `qwen3.5:4b`) — query_profile, focused_extract.
- `OLLAMA_SYNTH_MODEL` (default `batiai/gemma4-e4b:q4`) — final cited synthesis.
- `OLLAMA_EMBED` (default `embeddinggemma`) — rerank embeddings (MRR 0.724).
- `WEB_SYNTH_CLOUD_MODEL` (default `deepseek/deepseek-v4-flash`) — cloud fallback.
- API keys: `ZAI_API_KEY` / `Z_AI_API_KEY`, `MINIMAX_API_KEY`.
- `WEB_RESEARCH_TIMEOUT` (default 30s) — HTTP timeout override.

## Sibling ecosystem scripts (NOT in this repo)
- `WEB_RESEARCH_SCRIPTS` (alias `CHEAP_LLM_HOME`, default `~/.claude/scripts/`) →
  location of `ollama_client.py` (embed/generate/is_alive, used by
  ranking/intelligence/synthesis) and `cheap_llm.py` (cloud cascade,
  synthesis fallback). Both optional; graceful degrade when absent.

## Cache
On-disk JSON cache at `WEB_RESEARCH_CACHE_DIR` (default
`~/.cache/web-research/`), TTL `WEB_RESEARCH_CACHE_TTL` (default 3600s).
Bypass with `--no-cache`.

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
    ├── http.py                  HttpClient Protocol + UrllibHttpClient
    ├── cache.py                 schema-versioned on-disk cache
    └── ollama_api.py / formatters.py / results.py / ...

features/                        one responsibility per slice
    search/
      command.py                 mode_search
      engine.py                  thin dispatcher
      backends/{base,searxng,minimax,zai}.py
    read/
      command.py                 mode_read
      engine.py                  thin dispatcher + fallback chain
      backends/{base,firecrawl,zai_reader}.py
    research/command.py          orchestrator
    ranking/engine.py            rerank + source-quality
    intelligence/engine.py       query profile + expand + focused extract
    synthesis/engine.py          cited synthesis (Ollama local + cloud cascade)
```

Adding a new backend = one file under `backends/<name>.py` + one entry in
`BUILTIN_BACKENDS` / `BUILTIN_READERS`. Dispatcher never changes.

## Commands
- Install (dev): `uv sync --extra test` (editable install)
- Test: `uv run python -m pytest tests/ -q` (63 tests, network mocked) ·
  `--cov=web_research --cov-fail-under=85`
- Lint: `uv run ruff check src tests` · Format: `uv run ruff format --check .`
- Types: `uv run mypy src/`
- Smoke: `python3 shim.py search "test" -n 2`
