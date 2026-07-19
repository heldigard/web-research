# CONTEXT - Current State
> Updated: 2026-07-19 (controller quality + recency SHIPPED)

## What this is
Local-first web research engine for LLM agents. Graduated 2026-07-04 from
`~/.claude/scripts/web_research/` into `~/web-research/` (vertical-slice package).
Public: https://github.com/heldigard/web-research

## Active Focus
**Idle.** Shipped 2026-07-19 (this session):

### Controller quality
1. Empty-engine cascade free→paid (`search_with_escalation`)
2. Citation grounding on structured synthesis
3. Scrape window recovery past failed top-K
4. ES/whole-word query profiles; search exit 1 on empty
5. `research --json` pipeline diagnostics

### Recency / news (Fable-5 class failure)
1. Publish-date parse (field / URL `/YYYY/MM/DD/` / ISO title)
2. Recency weight in rerank; near-dup prefers newer
3. Scrape diversity for news; product-news profile
4. Sticky heuristic recency vs LLM; auto time_range=month
5. Synthesis timeline rules for conflicting deadlines
6. Live smoke: research finds July 19 Fable 5 extension (not July 12)

**Suite: ~168 tests**, ruff clean. Live stack OK.

## Architecture (stable)
- Vertical slices: `features/{search,read,research,ranking,intelligence,synthesis,status}/`
- Shared: `Settings` + `HttpClient` Protocol + schema-versioned disk cache
- Optional ecosystem: `WEB_RESEARCH_SCRIPTS` → `ollama_client` + `cheap_llm` shims

## Key decisions
- Zero runtime deps (stdlib only)
- Escalation free-first to protect paid quota
- Snippet body not used for publish date (event deadlines confuse recency)
- Month not week for auto recency filter (announce→extend chains)

## Next (optional)
- Shared model registry (proposals P2)
- Retrieval eval suite (MRR 0.724 baseline manual)
- Optional multi-hop follow-up search from `recommended_next_search`
- Semantic claim grounding (embed claim↔source) beyond lexical
