# web-research

Local-first web research engine for LLM coding agents (Claude Code, Codex,
Antigravity, OpenCode). The engine behind the cross-CLI "Web" tier:
**SearXNG → Firecrawl → Z.AI/MiniMax → Ollama rerank/synthesis → cheap cloud fallback**.

Graduated from `~/.claude/scripts/web_research/` into a standalone vertical-slice
package. Sibling projects: [`codeq`](https://github.com/heldigard/codeq),
[`smart-trim`](https://github.com/heldigard/smart-trim),
[`prompt-improve`](https://github.com/heldigard/prompt-improve).

## Why

LLM agents need current facts (docs, changelogs, CVEs, "2026 state of X") that
are not in training data. This engine gives them a free, private, self-hosted
research path before falling back to paid APIs:

| Tier | Source | Cost | Best for |
|------|--------|------|----------|
| 0 | SearXNG (`:8080`) | free | broad/general/fresh |
| 0 | Firecrawl (`:3002`) / Z.AI reader | free | read a specific URL |
| 0 | Ollama rerank (`:11434`) | free | noisy results, authority weighting |
| 1 | Z.AI / MiniMax direct APIs | subscription | citations, recency/domain filters |
| 2 | `cheap_llm.py` cloud cascade | PAYG | cited synthesis when Ollama is down |

## Install

```bash
git clone https://github.com/heldigard/web-research.git
cd web-research
uv sync            # or: pip install -e .[test]
```

## Local services (Ubuntu native)

The local-first path uses three self-hosted services. Bring them up once and
point the engine at them:

```bash
# SearXNG :8080 — meta-search (systemd or docker)
# Firecrawl :3002 — JS-rendering reader
# Ollama :11434 — local rerank + synthesis (GPU)
web-research status        # verify all three are reachable + models installed
```

`web-research status` is the operational complement to `capabilities`: it
actively probes the three services, cross-checks the configured Ollama models
(`OLLAMA_MODEL`, `OLLAMA_SYNTH_MODEL`, `OLLAMA_SYNTH_FALLBACK_MODEL`,
`OLLAMA_EMBED`) against the tags actually installed, and reports API-key,
cache, and cloud-fallback state. Use it to diagnose "why did research fall
back to cloud?" or "why was rerank skipped?" without curling each service.
It exits non-zero when any service is down, so scripts can gate on it.

If Firecrawl and Z.AI are unavailable, reads fall back to a stdlib HTML
extractor. Override service URLs with `SEARXNG_URL`, `FC_URL`, and
`OLLAMA_URL`.

## Usage

```bash
web-research search "rust async runtime 2026" -n 5 --rerank
web-research read https://example.com/docs --engine firecrawl
web-research read https://example.com/docs --engine html --no-robots
web-research research "what is claude code" -n 3 --scrape 2 --answer
web-research research "latest API behavior" --smart --json
web-research research "how rerank_results is used" --code-analyze
web-research capabilities
web-research status
```

| Subcommand | Does |
|------------|------|
| `search` | SearXNG, DuckDuckGo, Z.AI, or MiniMax → clean markdown results; `--smart` adds profiling and `--summary` a structured answer |
| `read` | One URL → markdown via Firecrawl, Z.AI, or the stdlib HTML reader; `--no-robots` explicitly bypasses the default robots gate |
| `research` | Search → scrape top K → Ollama/cloud synthesis with `[n]` citations; `--json` returns evidence/provenance and `--code-analyze` can add local `codeq` context |
| `status` | Probes SearXNG/Firecrawl/Ollama, cross-checks configured vs installed Ollama models, reports keys/cache/cloud-fallback; exits non-zero if a service is down |
| `capabilities` | Compact JSON tool cards for routers; no network probes |

Common flags: `--no-cache`, `--timeout N`, `--verbose`.

### Controller resilience (automatic)

- **Empty primary engine** → free→paid cascade (`searxng` ↔ `duckduckgo` →
  minimax/zai if keys); `search` exits `1` when still empty.
- **News / product windows** → recency-aware rerank (URL publish dates),
  near-dup keeps the newer article, scrape pool forces freshest hit;
  structured synthesis builds timelines when deadlines conflict.
- **Scrape failures** → window slides past dead top-K URLs until enough
  pages succeed or results are exhausted.
- **`--smart` facts** → lexical citation grounding demotes ungrounded claims.
- **`--smart` multi-hop** → one automatic follow-up search from
  `recommended_next_search` (disable with `--no-follow-up`).

## Configuration

The on-disk JSON cache defaults to `~/.cache/web-research/`. Configure it with:

- `WEB_RESEARCH_CACHE_DIR` and `WEB_RESEARCH_CACHE_TTL` (default 3600 seconds).
- `WEB_RESEARCH_CACHE_MAX_ENTRIES` (default 500) and
  `WEB_RESEARCH_CACHE_MAX_BYTES` (default 50 MB). A value of `0` disables that
  limit independently, so byte-only and entry-only budgets work as expected.
- `WEB_RESEARCH_HTTP_RETRIES` (default 2) and
  `WEB_RESEARCH_HTTP_BACKOFF` (default 0.2 seconds).

Valid cache hits update eviction recency without extending their serialized
TTL. Cache variants that change the artifact—such as reranking, robots policy,
or reader timeout—are isolated from one another. Use `--no-cache` to bypass
both reads and writes.

Readers respect `robots.txt` by default and fail open when it cannot be loaded.
`--no-robots` is an explicit per-command bypass; content fetched under that
policy is not reused by a later robots-respecting read.

## Ecosystem integration

The wired entry point is the shim at `~/.claude/scripts/web-research.py`, copied
from `shims/web-research.py`, which imports `web_research.cli.main` from this
project. Skills invoke it as
`python3 ~/.claude/scripts/web-research.py <cmd>`, so the 11 web/search router
skills (`web-search`, `search-smart`, `web-reader`, `web-research`, `searxng`,
`zai-search`, `minimax-search`, …) need no edits when the engine moves.

`cheap_llm.py` (the cloud cascade) is **not** part of this repo — it stays in
`~/.claude/scripts/` as shared infrastructure consumed by 8+ other tools. This
engine loads it optionally via `WEB_RESEARCH_SCRIPTS` (alias `CHEAP_LLM_HOME`; default `~/.claude/scripts`)
and degrades gracefully when absent.

## License

MIT
