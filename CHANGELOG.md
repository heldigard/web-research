# Changelog

All notable changes to `web-research` are documented here. The project stays
**zero-dependency, local-first** (stdlib only) — every enhancement below honors
that constraint.

## [Unreleased] — 2026-07-19

### Multi-hop follow-up + retrieval eval (2026-07-19)

- **Single follow-up hop** (`research --smart`): after structured synthesis,
  if `recommended_next_search` is a concrete query, run one extra
  search+scrape (≤2 pages), merge URL-deduped docs, and re-synthesize.
  Disable with `--no-follow-up`. Pipeline meta: `pipeline.follow_up`.
- **`synthesize_result`**: returns `{answer, structured}` for agent multi-hop
  without re-parsing markdown; `synthesize()` remains the string wrapper.
- **Offline retrieval eval** (`tests/test_retrieval_eval.py`): fixture gates
  for publish-date parse, near-dup→newer, recency MRR, diversity pick.
- Capabilities manifest documents the follow-up option.

### Recency / news correctness (2026-07-19)

- **Root cause of "missed July 19 extension"** (Fable 5 case): ranking used only
  semantic sim + domain quality; near-dup collapse kept the older headline;
  query `Fable 5 Anthropic` was classified evergreen; DDG leaves
  `publishedDate` empty so freshness was invisible.
- **Publish-date parse** from `publishedDate`, URL `/YYYY/MM/DD/`, title ISO
  (snippets ignored — they hold event deadlines, not publish days).
- **Recency mix-in** in `rerank_results` (`recency_weight` ~0.12 general,
  ~0.28 news); near-duplicates **prefer the newer** dated article.
- **Scrape diversity** for news: force-include freshest hit in top-K pool.
- **Product-news profile** — vendor + version/codename (`Fable 5 Anthropic`)
  and availability words (`extends`, `until`, `deadline`, …) set
  `needs_recency`.
- **Synthesis timeline rule** — conflicting dates/deadlines → explicit
  timeline; most recent dated source wins unless official primary contradicts.
- **Second-pass hardening**:
  - research auto `time_range` for recency is **month** (not week) so announce→extend chains stay visible
  - rule-based `needs_recency` / `intent=news` is **sticky** against casual LLM downgrades
  - product-news heuristic narrowed (no bare `google 3` FPs); title month-day without year is not treated as publish date
  - smart formatter shows `_pub_date` / `publishedDate` when known
  - live smoke: `research --smart "Fable 5 Anthropic extends"` cites **July 19** (not July 12)

### Controller quality (2026-07-19)

- **Empty-engine cascade** — `search` / `research` auto-escalate when the
  primary engine returns zero hits: free first (`searxng` ↔ `duckduckgo`),
  then paid engines with configured keys (`minimax`, `zai`). Matches the
  skill docs that already promised this. Human output notes the escalation;
  `research --json` exposes it under `pipeline.search`.
- **Search empty exit code** — `search` returns exit `1` when all engines
  in the cascade produce zero hits (controllers can branch without parsing
  markdown).
- **Citation grounding** — structured synthesis (`research --smart`,
  `search --smart --summary`) demotes facts whose claims lack lexical
  support in the cited source body to `confidence=low` and flags them
  `⚠ ungrounded`. Prevents local models from inventing citable claims.
- **Scrape recovery** — if the top-K scrape batch fails, the window slides
  to later ranked results until K pages succeed or the hit list is
  exhausted (no second full research call).
- **Query intelligence** — Spanish intent triggers (falló/comparar/noticias/…);
  whole-word matching so `"api"` no longer hijacks `"fastapi vs …"` as docs;
  language-aware preferred docs sites (Python/MDN/Rust/Go/Java).
- **Stricter synthesis prompts** — forbid invented versions/URLs/dates;
  require fact↔source support; prefer decision-ready answer style for agents.

### Ubuntu-native correctness (2026-07-18)

- **DuckDuckGo bot-challenge bypass** — `html.duckduckgo.com` now returns a
  captcha page for bare scrapers. The DDG backend sends Accept /
  Accept-Language / Referer headers (still project UA; full browser UAs
  worsen challenge rates) and detects challenge HTML so agents get an
  explicit stderr warning instead of silent empty results.
- **Search fallback policy** — SearXNG free-breadth merge is now limited to
  paid engines (`minimax`, `zai`), matching the documented intent. Selecting
  `--engine duckduckgo` no longer silently labels SearXNG hits as the result
  source when DDG fails.
- **CLI network error hint** points at `web-research status` (Ubuntu-native
  stack) instead of `docker ps`.
- Docs: `CLAUDE.md` model defaults + `status` subcommand aligned with live
  `config.py` / README.

### Correctness hardening (2026-07-12)

- Cache entry and byte budgets are now independent: `0` disables only that
  axis instead of accidentally imposing a one-entry cap. Valid reads promote
  recency by mtime, while TTL remains based on the serialized timestamp.
- Failed atomic cache writes no longer trigger eviction of healthy entries;
  equal mtimes use path ordering for deterministic victim selection.
- Search caches distinguish reranked from unranked results. Read caches
  distinguish robots policy and reader timeout, preventing `--no-robots`
  content from satisfying a later robots-respecting invocation.
- LLM query profiles are normalized field by field, so valid JSON with invalid
  types degrades to deterministic defaults instead of crashing smart flows.
- Common CLI settings reload from environment on every embedded `main()` call,
  preventing `--timeout` and `--verbose` from leaking into later calls.

### Resilience
- **HTTP retry/backoff (stdlib)** — `UrllibHttpClient._request` now retries
  transient failures (HTTP `429`, `5xx`, and `URLError` such as timeouts /
  connection resets) with exponential backoff. Non-retryable `4xx` surfaces
  immediately. Config: `WEB_RESEARCH_HTTP_RETRIES` (default `2`),
  `WEB_RESEARCH_HTTP_BACKOFF` (default `0.2`s). (`shared/http.py`,
  `shared/config.py`)
- **Cache size-bound LRU eviction** — `cache.set()` now sweeps oldest entries
  by mtime when entry-count or byte budgets are exceeded, so the cache dir
  no longer grows unbounded. Config: `WEB_RESEARCH_CACHE_MAX_ENTRIES`
  (default `500`, `0` = no limit), `WEB_RESEARCH_CACHE_MAX_BYTES` (default
  `50 MB`, `0` = no limit). (`shared/cache.py`, `shared/config.py`)

### Crawl compliance
- **robots.txt gate** — `read_with_fallback` checks `robots.txt` before
  fetching and skips disallowed URLs. Fails open (allows) when robots is
  unreachable/malformed. Bypass with `--no-robots` (`read`, `research`).
  New module `shared/robots.py` (stdlib `urllib.robotparser`, per-host
  5-min cache).

### Ranking quality
- **Authority domains extracted to a data file** — `source_quality_score`'s
  hardcoded domain set moved to
  `features/ranking/data/authority_domains.txt`, loaded via
  `importlib.resources`. The list grows without touching engine code.
  Matching semantics (incl. the `evil-docs.python.org` ≠ `docs.python.org`
  guard) are unchanged.
- **Stopword/punctuation-aware overlap** — `query_word_overlap` now lowercases,
  strips punctuation, and drops stopwords + single chars, so `"rust?"` and
  `"rust"` no longer count as different tokens.
- **Optional TEI cross-encoder rerank (stage 2)** — when `TEI_RERANK_URL` is
  set (e.g. `http://localhost:8081`, HuggingFace TEI `/rerank` appliance with
  `bge-reranker-v2-m3`), `rerank_results` re-orders survivors with a joint
  `(query, doc)` cross-encoder on top of the bi-encoder cosine rank. Disabled
  or unreachable → transparent no-op. (`features/ranking/tei_rerank.py`)

### Reader robustness
- **Stdlib HTML reader** — new `html` backend (`features/read/backends/html.py`)
  does a plain `GET` + `html.parser` extraction as a zero-dep, no-key,
  no-JS last resort. It is always appended to the reader fallback chain so
  `read`/`research` never return empty just because Firecrawl + Z.AI are down.
- `read_with_fallback` chain is now `requested → Firecrawl → Z.AI → HTML`.
- `mode_read` unified onto `read_with_fallback` (removed a duplicated chain).

### New search backend
- **DuckDuckGo (zero-dep, anonymous)** — new `duckduckgo` engine
  (`features/search/backends/duckduckgo.py`) scrapes `html.duckduckgo.com/html/`
  with the stdlib `html.parser`, unwrapping the `/l/?uddg=` redirect to the
  canonical URL. Free, no API key. Available on `search` and `research`.

### Synthesis robustness
- **Tolerant structured-JSON extraction** — `_render_structured` now finds the
  first brace-balanced JSON object (string-aware) even when wrapped in prose
  or ```` ```json ```` fences, instead of requiring a clean top-level object.
  Falls back to raw text on failure.

### CLI
- `search`/`research` `--engine` accept `duckduckgo`.
- `read` `--engine` accepts `html`; `read` and `research` accept `--no-robots`.
- `research` accepts `--code-analyze` (see Cross-CLI integration below).

### Cross-CLI integration
- **`research --code-analyze`** — opt-in fusion of web research with local code
  intelligence. Identifier-like tokens from the query are looked up in the
  current working directory via the `codeq` CLI (`find` + `refs`); resolved hits
  are appended to each scraped doc as a `## Local code context (codeq)` section
  before synthesis, so the answer weaves web prose with how the symbol is
  actually used in the caller's own repo. Degrades to a no-op when `codeq` is
  absent or no symbol resolves locally (the common case for third-party library
  docs). Honest scope: `codeq` operates on the local repo, not on scraped text.
  New module `features/intelligence/code_analyze.py`.

### Tests
- New `tests/test_enhancements.py` (41 tests) covering every item above with
  the network mocked or via pure functions. Total suite now 108 tests.

### Notes
- Ollama has **no native `/rerank` endpoint** in 2026 (only `/api/embed`), so
  the cross-encoder stage targets a dedicated TEI server rather than Ollama.
- `asyncio`, `instructor`, `diskcache`, `trafilatura`, `tenacity`, and
  cloud rerank APIs were deliberately **not** added: the stdlib equivalents
  above cover the same gaps without breaking the zero-dependency invariant
  (YAGNI until a gap is measured as a real bottleneck).

### Debt cleanup
- **Removed dead code from `shared/http.py`** — `codescan dead` + `codeq refs`
  confirmed four unreferenced symbols (0 callers repo-wide, src + tests):
  `set_default_client` (the aspirational swap setter never called — tests mock
  `urllib.request.urlopen` instead), and the three legacy back-compat helpers
  `_http` / `_get_json` / `_post_json` (plus the `_encode_query` alias) whose
  "kept for existing call sites" comment was stale — the backend-split refactor
  migrated every call site to `default_client()`. `default_client` itself is
  retained (every backend resolves through it). The future-httpx swap is now
  documented honestly as "edit the `_client` assignment" rather than a setter
  that nothing calls. `ARCHITECTURE.md` swap recipe updated. Suite stays
  108/108; `codescan dead` drops 28 → 24 (the residual 24 are confirmed false
  positives: HTMLParser framework callbacks, config-surface settings read via
  the `Settings` proxy, and test-only cache-bust helpers — static-analysis
  limits, not debt).
