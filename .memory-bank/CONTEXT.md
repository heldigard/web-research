# CONTEXT - Current State
> Updated: 2026-07-18 (status command + consistency fixes SHIPPED locally)

## What this project is
The `web_research` engine extracted from `~/.claude/scripts/web_research/`
(flat 13-module package, 1302 LOC) into a standalone vertical-slice project at
`~/web-research/`. Mirrors the `codeq` / `smart-trim` / `prompt-improve`
graduation pattern.

## Active Focus
STATUS COMMAND + CONSISTENCY FIXES SHIPPED (2026-07-18): added the operational
`web-research status` subcommand — the network-active complement to
`capabilities`. It probes SearXNG/Firecrawl/Ollama in parallel (bounded 3 s
timeout, injectable HttpClient), cross-checks the four configured Ollama models
against `/api/tags` (tag-tolerant: bare name ⇒ `:latest`), and reports key /
cache / cloud-fallback state; exits non-zero when a service is down so scripts
can gate on it. Two consistency fixes shipped alongside: `schema_version`
literal `1` → `SCHEMA_VERSION` constant in `research/command.py`, and the dead
`web_synth_max_context_chars` dataclass default aligned 14000 → 40000 (matches
`load_settings` since fce82d9). Suite now **139 tests**, 90% coverage, status
module 96%; Ruff + Pyright clean, codescan all 0. Changes local/uncommitted on
`main`.

## What this project is
The `web_research` engine extracted from `~/.claude/scripts/web_research/`
(flat 13-module package, 1302 LOC) into a standalone vertical-slice project at
`~/web-research/`. Mirrors the `codeq` / `smart-trim` / `prompt-improve`
graduation pattern.

## Active Focus
CACHE + CLI RESILIENCE AUDIT COMPLETED (2026-07-12): cache budgets/LRU and
policy-aware keys corrected; LLM query profiles normalized; embedded CLI
settings made reentrant; machine capability cards enriched with additive
option metadata. Suite now **125 tests**, 89.30% coverage, Ruff + mypy clean,
build green, and codescan reports 0 secrets/SAST/dead/lint/type/architecture
findings. Changes remain local/uncommitted on `feat/zero-dep-enhancements`.

## Recent Changes (2026-07-12 — audit hardening)
- Cache: `0` independently disables entry/byte limits; valid hits promote
  mtime without extending serialized TTL; deterministic `(mtime, path)`
  eviction; failed writes no longer evict healthy entries.
- Cache correctness: search keys separate `--rerank`; read keys separate
  robots policy and `--zai-timeout`, preventing bypassed content reuse.
- Intelligence: LLM profile output is normalized field-by-field and direct
  query helpers skip malformed values; valid empty preferred-site lists remain
  empty.
- CLI: `apply_common()` reloads environment-derived Settings per invocation,
  preventing timeout/verbose leakage in embedded callers.
- Agent-native contract: schema-v1 capability cards now include additive,
  machine-readable option/policy metadata while preserving all prior fields.
- Docs: README/CLAUDE/CHANGELOG aligned with current engines and flags.

## Recent Changes (2026-07-08 — enhancement batch)
- Resilience: stdlib HTTP retry/backoff (`UrllibHttpClient`, env
  `WEB_RESEARCH_HTTP_RETRIES`/`_BACKOFF`); cache size-bound LRU eviction
  (`WEB_RESEARCH_CACHE_MAX_ENTRIES`/`_MAX_BYTES`).
- Compliance: `robots.txt` gate (`shared/robots.py`, fail-open, `--no-robots`).
- Ranking: authority domains → `ranking/data/authority_domains.txt`
  (`importlib.resources`); stopword/punct-aware `query_word_overlap`;
  optional TEI cross-encoder stage-2 (`ranking/tei_rerank.py`, env
  `TEI_RERANK_URL` — Ollama has no native `/rerank` in 2026).
- Reader: stdlib `HtmlReader` (`html.parser`) as zero-dep last-resort,
  appended to the fallback chain (`requested → Firecrawl → Z.AI → HTML`).
  `mode_read` unified onto `read_with_fallback`.
- Search: zero-dep anonymous `duckduckgo` backend (unwraps `/l/?uddg`).
- Synthesis: tolerant `_extract_json_object` (brace-balanced, prose/fence-aware).
- CLI: `--engine duckduckgo` (search/research), `--engine html` +
  `--no-robots` (read).
- Deliberately NOT added (YAGNI / zero-dep): asyncio, instructor, diskcache,
  trafilatura, tenacity.

## Recent Changes (2026-07-05)
- Split `features/{search,read}/engine.py` into thin dispatchers + new
  `backends/<name>.py` per source (SearXNG / MiniMax / Z.AI; Firecrawl /
  Z.AI reader). Adding a new backend is now one file + one registry line.
- Replaced module-level config globals with a frozen `Settings` dataclass
  + env loader (`get_settings()` / `reload_settings(**overrides)`).
  Externalized `MINIMAX_URL`, `ZAI_SEARCH_URL`, `ZAI_READER_URL` to env.
  Legacy SCREAMING_CASE names readable via `__getattr__` proxy for BC.
- Introduced `HttpClient` Protocol + `UrllibHttpClient` default impl.
  Backends resolve `default_client()` at call time → a future `httpx` swap
  changes the module singleton assignment, with zero backend edits.
- Cache entries stamped with `SCHEMA_VERSION` + optional `engine_tag`.
  Bumping model or prompt auto-invalidates stale entries without code.
- Added CI gates: `ruff format --check` + `mypy src/` + `--cov --cov-fail-under=85`.
- New `BackendSliceTests` class validates the new architecture end-to-end
  (registry, dataclass shape, URL canonicalization, schema-version
  cache invalidation, typed-config reload) without HTTP.

## Previous milestone (2026-07-04 graduation, SHIPPED)
- Repo: https://github.com/heldigard/web-research (public)
- 37→63 tests, all green; live SearXNG verified.
- Restructured flat modules into vertical slices; per-mode `command.py`.
- Module aliases (`wr.search` / `wr.reader` / `wr.synthesis`) preserve
  test patch paths through the restructure.
- Shim reconnection via `~/.claude/scripts/web-research.py` →
  `WEB_RESEARCH_HOME` env (zero skill edits across 11 web/* routers).

## Key decision: cheap_llm + ollama_client STAY in ~/.claude/scripts/
Shared infrastructure used by 8+ other tools (commit-draft, pr-draft,
diff-review, test-triage, error-classify, pdf-extract-structured,
intent_route, extract-tool-output). This engine loads them OPTIONALLY
via `WEB_RESEARCH_SCRIPTS` (alias `CHEAP_LLM_HOME`) and degrades gracefully.

## Blockers / Risks
- None. All quality gates green; live smoke (SearXNG `:8080`) returns
  real Rust-2026 results through the new split architecture.

## Next Steps
- cheap_llm.py graduation (separate future project — 33KB, 8+ consumers).
- Live-model re-bench if `OLLAMA_SYNTH_MODEL` / `OLLAMA_EMBED` change.
- Optional: ship the `httpx` HttpClient impl behind a feature flag (would
  supersede the stdlib retry loop with connection pooling + async).
- Optional: add a `ragas`/`promptfoo` eval suite to regression-test retrieval
  quality (the "MRR 0.724" baseline is currently manual).
