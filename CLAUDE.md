# Project: web-research

`web-research` — local-first web research engine for LLM agents. Public repo:
https://github.com/heldigard/web-research

Graduated from `~/.claude/scripts/web_research/` (flat 13-module package) into
its own vertical-slice project, mirroring the `codeq` / `smart-trim` /
`prompt-improve` layouts.

## What it is

The engine behind the ecosystem's **local-first web/research stack** (the "Web"
tier of the cross-CLI MCP priority): skill `web-search` → this engine
(SearXNG local → MiniMax/Z.AI direct APIs → Ollama rerank → `cheap_llm.py`
cloud cascade). The 11 web/search skills are thin routers; this is the engine.

## Architecture: vertical-slice CLI package

```
src/web_research/
  cli.py                thin wiring: build_parser + dispatch (handlers injected)
  shared/               config, http, ollama_api, cache, formatters,
                        cli_helpers (_apply_common), results (dict transforms)
  features/
    search/    command.py (mode_search)  + engine.py (searxng/zai/minimax backends)
    read/      command.py (mode_read)    + engine.py (firecrawl/zai_reader/scrape_with_fallback)
    research/  command.py (mode_research — orchestrates search+rank+read+synth)
    ranking/   engine.py (rerank_results, source_quality_score)
    intelligence/ engine.py (query_profile, expand_queries, focused_extract)
    synthesis/ engine.py (synthesize, _render_structured; cheap_llm fallback)
```

One responsibility per feature folder (cohesion > size). Engine modules are
single cohesive files (~60-175 LOC), not over-split. `cli.py` is the only file
that split (the old 255-LOC version mixed 3 mode handlers → one `command.py`
per CLI mode).

## Entry points

- **Wired ecosystem shim**: `~/.claude/scripts/web-research.py` → imports
  `web_research.cli.main` from here (env `WEB_RESEARCH_HOME`, default this dir).
  Skills call `python3 ~/.claude/scripts/web-research.py <cmd>` — the shim
  preserves that contract, so the 11 skills need zero edits.
- **PATH symlink**: `~/.local/bin/web-research` → the shim.
- **Console script** (`pip install -e .`): `web-research`.
- **Local dev**: `python3 shim.py <cmd>`.

## CLI

```
web-research search  <query> [-n 8] [--engine searxng|zai|minimax|duckduckgo]
                             [--cat general] [--lang en] [--time day|week|month|year]
                             [--rerank] [--smart] [--summary] [--json]
web-research read    <url>   [--engine firecrawl|zai|html] [--no-robots]
                             [--max-chars N] [--wait N] [--zai-timeout N]
web-research research <query> [-n 6] [--scrape 3]
                             [--engine searxng|zai|minimax|duckduckgo] [--time ...]
                             [--answer] [--smart] [--max-chars N] [--no-robots]
                             [--code-analyze] [--json]
web-research status        # probe SearXNG/Firecrawl/Ollama + models/keys/cache
web-research capabilities  # machine-readable router contract; no network probes

Common: --no-cache --timeout N --verbose
```

## Conventions

- Vertical slices in `src/web_research/features/<feature>/`; shared infra in
  `src/web_research/shared/`. Shared NEVER imports from features (low coupling).
- **Absolute imports** rooted at `web_research` (not relative) — clearer across
  the nested feature layout.
- **cheap_llm.py graduated to `~/cheap-llm/`** (standalone project,
  github.com/heldigard/cheap-llm). Shim at `~/.claude/scripts/cheap_llm.py`
  re-exports from there. Consumed as an OPTIONAL fallback via
  `WEB_RESEARCH_SCRIPTS` env (alias `CHEAP_LLM_HOME` for back-compat;
  default `~/.claude/scripts`); graceful degrade if absent.
- External services: SearXNG `:8080`, Firecrawl `:3002`, Ollama `:11434`.

## Commands

- Install (dev): `uv sync` (or `pip install -e .[test]`)
- Test: `python3 -m pytest tests/ -q`
- Lint: `ruff check src` · Format: `ruff format --check src`
- Smoke: `python3 shim.py search "test" -n 2`

## Model routing

- **Local (Ollama)**: `OLLAMA_MODEL` (default `cryptidbleh/gemma4-claude-opus-4.6:latest`)
  for query_profile/focused_extract; `OLLAMA_SYNTH_MODEL`
  (`hf.co/TeichAI/Qwen3.5-9B-Fable-5-v1-GGUF:Q4_K_M`) for the final cited
  synthesis; `OLLAMA_SYNTH_FALLBACK_MODEL` for the local secondary when primary
  fails; `OLLAMA_EMBED` (`embeddinggemma`) for semantic rerank.
- **Cloud fallback**: `WEB_SYNTH_CLOUD_MODEL` (`deepseek/deepseek-v4-flash`) via
  `cheap_llm.py` — fires only when local Ollama is down.
- Diagnose live wiring with `web-research status` (probes services + models).
