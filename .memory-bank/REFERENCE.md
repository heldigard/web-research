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
| Service | Default URL | Env override |
|---------|-------------|--------------|
| SearXNG | http://localhost:8080 | `SEARXNG_URL` |
| Firecrawl | http://localhost:3002 | `FC_URL` + `FC_API_KEY` |
| Ollama | http://localhost:11434 | `OLLAMA_URL` |

## Model routing
- `OLLAMA_MODEL` (default `qwen3.5:4b`) — query_profile, focused_extract.
- `OLLAMA_SYNTH_MODEL` (default `batiai/gemma4-e4b:q4`) — final cited synthesis (web_synth #1, re-bench 2026-07-04).
- `OLLAMA_EMBED` (default `embeddinggemma`) — rerank embeddings (MRR 0.724).
- `WEB_SYNTH_CLOUD_MODEL` (default `deepseek/deepseek-v4-flash`) — cloud fallback via cheap_llm, fires only when Ollama is down.
- API keys: `ZAI_API_KEY` / `Z_AI_API_KEY`, `MINIMAX_API_KEY`.

## Sibling ecosystem scripts (NOT in this repo)
`ECOSYSTEM_SCRIPTS` env (default `~/.claude/scripts/`) — location of:
- `ollama_client.py` — embed/generate/is_alive (used by ranking, intelligence, synthesis).
- `cheap_llm.py` — cloud cascade (used by synthesis as fallback).
Both optional; engine degrades gracefully when absent.

## Cache
On-disk JSON cache at `WEB_RESEARCH_CACHE_DIR` (default `~/.cache/web-research/`),
TTL `WEB_RESEARCH_CACHE_TTL` (default 3600s). Bypass with `--no-cache`.

## Commands
- Install (dev): `uv sync --extra test` (editable install)
- Test: `uv run python -m pytest tests/ -q` (37 tests, network mocked)
- Lint: `uv run ruff check src tests` · Format: `uv run ruff format --check src tests`
- Smoke: `python3 shim.py search "test" -n 2`
