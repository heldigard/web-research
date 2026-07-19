# CONTEXT - Current State
> Updated: 2026-07-19 (multi-hop + retrieval eval SHIPPED)

## What this is
Local-first web research engine for LLM agents. Public:
https://github.com/heldigard/web-research

## Active Focus
**Idle.** Latest (2026-07-19):

1. Controller quality — cascade, grounding, scrape recovery, ES profiles
2. Recency ranking — publish-date parse, near-dup newer, sticky news profile
3. **Multi-hop** — `--smart` one follow-up from `recommended_next_search`
   (`--no-follow-up` to skip); `synthesize_result` returns structured meta
4. **Retrieval eval** — offline fixture suite (`tests/test_retrieval_eval.py`)

**Live smoke**: Fable-5 research cites July 19 extension.
**Suite**: full green (follow-up + retrieval eval included).

## Key decisions
- Zero runtime deps (stdlib only)
- Max **one** follow-up hop (cost-bounded for agent loops)
- Snippet deadlines ≠ publish dates; CMS URL dates preferred
- Month auto time_range for recency queries

## Next (optional)
- P2 shared model registry
- Embed-based claim grounding
- Expand retrieval eval with more fixtures / real MRR corpus
