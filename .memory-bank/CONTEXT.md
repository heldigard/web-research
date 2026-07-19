# CONTEXT - Current State
> Updated: 2026-07-18 (Ubuntu-native DDG + status SHIPPED, memory hygiene)

## What this is
Local-first web research engine for LLM agents. Graduated 2026-07-04 from
`~/.claude/scripts/web_research/` into `~/web-research/` (vertical-slice package).
Public: https://github.com/heldigard/web-research

## Active Focus
**Idle.** Latest ship (2026-07-18, this session):

1. **`web-research status`** — probes SearXNG/Firecrawl/Ollama, model
   cross-check, keys/cache/cloud; exit ≠0 if a service is down.
2. **DDG correctness** — Accept/Accept-Language/Referer avoids anomaly
   captcha; challenge HTML → stderr warn + empty list.
3. **Search fallback** — SearXNG free-breadth merge only for paid engines
   (`minimax`, `zai`). `--engine duckduckgo` no longer silently returns
   searxng-labeled hits.
4. CLI network hint → `web-research status` (not `docker ps`).

**Suite: 144 tests**, ruff/pyright clean. Live stack OK on Ubuntu native.

## Architecture (stable)
- Vertical slices: `features/{search,read,research,ranking,intelligence,synthesis,status}/`
- Shared: `Settings` + `HttpClient` Protocol + schema-versioned disk cache
- Optional ecosystem: `WEB_RESEARCH_SCRIPTS` → `ollama_client` + `cheap_llm` shims
- Details: `ARCHITECTURE.md`, `topics/code-architecture.md`, `systemPatterns.md`

## Key decisions
- Zero runtime deps (stdlib only). No asyncio / diskcache / trafilatura.
- `cheap_llm` + `ollama_client` graduated sibling projects; loaded via shims.
- Cache schema bump invalidates on-disk entries; `engine_tag` for model swaps.

## Next (optional, not in flight)
- Shared model registry across harness projects (`docs/proposals.md` P2)
- Retrieval-quality eval suite (MRR 0.724 baseline is manual)
- Optional `httpx` HttpClient behind a flag
