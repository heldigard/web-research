# Progress
> Compact milestone log. Verbose session dumps → `topics/session-handoffs.md`.

## 2026-07-18 — Ubuntu-native ops + DDG correctness
- **feat(status)**: `web-research status` probes SearXNG/Firecrawl/Ollama,
  model cross-check (tag-tolerant), keys/cache/cloud; exit ≠0 if down.
- **fix(search)**: DDG Accept/Accept-Language/Referer + challenge detection;
  SearXNG free-breadth fallback only for paid engines (`minimax`/`zai`).
- **fix(cli)**: network error hint → `web-research status`.
- Docs: CLAUDE models + status; CHANGELOG; memory hygiene.
- Validated: **144 tests**, ruff/pyright clean, live DDG + stack smoke.

## 2026-07-14/15 — Cache + context budgets
- Research scrape + synthesis disk cache (`scrape` / `synth` prefixes).
- `SCHEMA_VERSION` constant used in capabilities/research JSON envelopes.
- `WEB_SYNTH_MAX_CONTEXT_CHARS` 14k→40k; research `--max-chars` default 12k.
- Suite 134→138.

## 2026-07-12 — Cache/CLI resilience audit
- Independent cache budgets (`0` disables one axis); true mtime LRU.
- Search/read cache keys separate rerank / robots / zai-timeout.
- LLM query profiles normalized; `apply_common()` reloads Settings.
- Capability cards: additive `options` metadata (schema v1).
- Plan: `docs/plans/2026-07-12-001-fix-cache-cli-resilience-plan.md`. Suite 125.

## 2026-07-08/09 — Zero-dep batch + ecosystem
- HTTP retry/backoff, robots gate, authority domains file, TEI optional
  rerank, HtmlReader, DuckDuckGo backend, tolerant JSON extract.
- P1: ollama_client graduated (`github.com/heldigard/ollama-client`); 3/4
  consumers on `require('1.0')`; codeq still on shim by design.
- P4: `research --code-analyze` via codeq. Dead HTTP helpers removed.
- Suite 93→108.

## 2026-07-05 — Architecture refactor
- Settings dataclass + HttpClient Protocol + schema-versioned cache.
- Search/read backends split to one file per source.
- CI: ruff format + mypy + cov≥85%. ARCHITECTURE.md. Suite 63.

## 2026-07-04 — Graduation
- Extracted from `~/.claude/scripts/web_research/` → `~/web-research/`.
- Vertical slices + per-mode `command.py`; public GitHub repo; shim wired.
- 2026-07-19T01:41:31Z | status:completed | session:gen:ac1eab60-6b6b-4475-9d73-c192e656c771 | claude: Shared model registry (proposals P2) if cross-repo model drift hurts again
- 2026-07-19T16:26:15Z | 2026-07-19: Controller quality SHIPPED — search_with_escalation free→paid cascade; ground_structured_facts for --smart synthesis; scrape window recovery; ES+whole-word query profiles; search exit 1 on empty; research pipeline JSON; ~156 tests green.
- 2026-07-19T16:43:42Z | 2026-07-19: Recency fix SHIPPED — Fable-5 class failure (old July 7/12 headline beat July 19 update). parse_result_date+recency_weight+near-dup prefers newer+scrape diversity+sticky needs_recency+time_range month. Live smoke: research --smart cites July 19. Full controller-quality batch (cascade/grounding/scrape recovery) same session.
- 2026-07-19T16:45:38Z | status:completed | session:gen:d73e2ece-9819-41a9-a1c6-5c25b62ade47 | claude: Engine cascade, grounding, scrape recovery, ES profiles
- 2026-07-19T16:49:53Z | 2026-07-19: Multi-hop SHIPPED — research --smart runs ≤1 follow-up hop from recommended_next_search (+2 scrapes, re-synth); --no-follow-up disables. synthesize_result returns structured meta. Offline retrieval eval (parse/near-dup/MRR/diversity). Suite green.
