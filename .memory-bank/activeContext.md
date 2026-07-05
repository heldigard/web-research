# Active Context

## 2026-07-05 — ARCHITECTURE REFACTOR SHIPPED

Split `features/{search,read}/engine.py` into thin dispatchers + per-backend
file slices (search: SearXNG / MiniMax / Z.AI; read: Firecrawl / Z.AI
reader). Upgraded `shared/` to a typed `Settings` dataclass, an
`HttpClient` Protocol with `UrllibHttpClient` default (swap to httpx
is one setter call), and a schema-versioned on-disk cache that
auto-invalidates on model/prompt changes. CI now runs `ruff format
--check` + `mypy src/` + `--cov --cov-fail-under=85`. 63 tests pass,
coverage 89%. Live SearXNG smoke returns real results. See progress.md
for the full milestone list and systemPatterns.md for the new patterns.

## 2026-07-04 — GRADUATION COMPLETE (earlier milestone)

`~/web-research/` vertical-slice project, public at
github.com/heldigard/web-research. Ecosystem reconnected via the shim
at `~/.claude/scripts/web-research.py`. Restructured flat modules into
vertical slices (`features/{search,read,research,ranking,intelligence,
synthesis}/` + `shared/`). Module aliases preserve test patch paths.
See progress.md for the full milestone list.
