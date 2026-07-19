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
