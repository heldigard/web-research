---
title: "fix: Harden cache and CLI resilience"
type: fix
status: completed
date: 2026-07-12
---

# fix: Harden cache and CLI resilience

## Overview

Correct reproducible cache-policy defects and harden the reusable CLI paths without
adding dependencies or changing the vertical-slice architecture. The work covers cache
eviction semantics, access recency, option-aware cache keys, defensive normalization of
LLM-generated query profiles, reentrant common CLI flags, and CLI documentation drift.

## Enhancement Summary

**Deepened on:** 2026-07-12  
**Review lenses:** performance, Python correctness, code simplicity, flow analysis,
official Python documentation

### Key improvements

1. The cache algorithm is now specified as one independent-budget predicate, true
   access-recency by metadata touch, deterministic ordering, and eviction only after a
   successful atomic write.
2. LRU tests use explicit nanosecond mtimes rather than sleeps and derive byte budgets
   from actual cache file sizes.
3. Profile hardening uses one private runtime normalizer instead of a public static type
   layer; direct helper calls remain defensive.
4. Multiprocess cache behavior is explicitly best-effort and lock-free; strict cross-
   process LRU is outside this bounded correction.

### New considerations discovered

- A metadata write is added to each valid cache hit. This is O(1) and acceptable for a
  local cache; eviction remains O(n log n) after writes and is bounded by the default
  500-entry budget.
- TTL remains based on the serialized `entry["ts"]`, never file mtime, so promoting an
  entry does not extend its freshness.
- A failed cache write must not evict unrelated healthy entries.
- Existing quality-sensor warnings are baseline/static-analysis limitations; the gate is
  no new actionable findings in touched code.

## Problem Statement

The current implementation passes 115 tests and has 88% coverage, but the audit found
behavioral gaps not represented in the suite:

- `WEB_RESEARCH_CACHE_MAX_ENTRIES=0` is documented as disabling the entry-count limit,
  yet `max(max_entries, 1)` silently reduces the cache to one entry whenever a byte
  budget is active.
- Eviction claims LRU behavior, but successful reads never update file recency; the
  implementation is effectively oldest-write-first.
- `read --no-robots` shares a cache key with the default robots-respecting flow, allowing
  bypassed content to be returned later without reapplying the compliance gate.
- `search --rerank` shares a cache key with an unranked search, so either mode can reuse
  results produced by the other.
- A syntactically valid but incorrectly typed LLM profile can raise `AttributeError` in
  smart search/research instead of degrading to the deterministic profile.
- `--timeout` and `--verbose` mutate module attributes and leak into later `main()` calls
  in the same process while disagreeing with the typed `Settings` singleton.
- `CLAUDE.md` and `README.md` omit current engines and flags, and one committed test file
  fails `ruff format --check`.

## Research Summary

### Local evidence

- Cache limits and eviction: `src/web_research/shared/cache.py`.
- Typed settings and environment reload: `src/web_research/shared/config.py` and
  `src/web_research/shared/cli_helpers.py`.
- Search/read cache construction: `src/web_research/features/search/command.py` and
  `src/web_research/features/read/command.py`.
- Smart-profile consumers: `src/web_research/features/intelligence/engine.py`.
- CLI source of truth: `src/web_research/cli_parser.py`.
- Institutional guidance: `.memory-bank/topics/code-architecture.md`,
  `.memory-bank/REFERENCE.md`, and `.memory-bank/progress.md`.
- No `docs/solutions/` knowledge base exists in this repository.

### External research decision

Limited to primary Python documentation because the defects are locally reproducible and
stdlib-only. Python documents `os.utime(path, times=None)` as the direct mechanism for
updating file timestamps, and documents that type annotations/`TypedDict` are not runtime
validation. Those facts support a best-effort metadata touch plus explicit runtime
normalization rather than a new validation dependency.

- Python `os.utime`: https://docs.python.org/3/library/os.html#os.utime
- Python `typing.TypedDict`: https://docs.python.org/3/library/typing.html#typing.TypedDict
- Python `NamedTemporaryFile`: https://docs.python.org/3/library/tempfile.html#tempfile.NamedTemporaryFile

## Proposed Solution

### 1. Correct cache budgets and LRU recency

- Evaluate entry-count and byte budgets independently; a value `<= 0` disables only
  that axis.
- Express the over-budget predicate once so pre-check and eviction loop cannot drift.
- Touch a valid cache file after schema and TTL validation, swallowing `OSError` so a
  metadata failure never turns a hit into a miss.
- Sort eviction candidates deterministically by `(mtime, path)`.
- Preserve strict byte budgets: a single oversized entry may evict itself.
- Run eviction only after an atomic replacement succeeds, avoiding unrelated eviction
  after a failed write.
- Keep TTL validation tied to the serialized timestamp rather than mtime.
- Keep the cache lock-free and best-effort across processes; do not introduce a sidecar
  index, persistent access log, or file-locking dependency.

### 2. Isolate cache variants that change behavior

- Add `rerank` to search cache parameters.
- Add `zai_timeout` and `respect_robots` to read cache parameters.
- Remove `summary` from search cache parameters because it changes only post-cache
  synthesis/rendering, not the cached search-result artifact.
- Keep `max_chars` out of the read key because truncation occurs after full markdown is
  retrieved from cache.
- Keep `--no-cache` out of keys because it bypasses cache reads and writes entirely.

### 3. Normalize LLM query profiles

- Add one private `_normalize_profile(raw: object, fallback: dict[str, object])` runtime
  boundary; avoid a public profile model or dependency.
- Normalize every field from model output against the deterministic profile:
  real booleans only, known enum strings only, and non-empty string lists only.
- Discard unknown fields and fall back per field rather than rejecting an otherwise
  useful profile wholesale.
- Return a new dictionary rather than mutating caller or model data.
- Make `expand_queries` and `search_queries` defensive when called directly with a
  caller-supplied mapping: never call `.strip()` on a non-string and never stringify
  arbitrary site-filter objects.

### 4. Make common flags reentrant

- Make `apply_common()` call `config.reload_settings()` on every command invocation.
- Pass only explicit CLI overrides; absent flags re-resolve their environment/default
  values, preventing state from leaking between embedded calls.
- Preserve environment values such as `WEB_RESEARCH_VERBOSE=true` when the flag is
  absent.

### 5. Align docs and quality gates

- Update `CLAUDE.md` and `README.md` from the parser's current command surface:
  DuckDuckGo, HTML fallback, robots policy, structured JSON, and code analysis.
- Document the independent `0 = unlimited` cache-limit semantics.
- Apply Ruff formatting to the touched test file.

## System-Wide Impact

### Interaction graph

- `main()` parses command → mode handler calls `apply_common()` → settings reload from
  environment plus explicit overrides → backends resolve current settings at runtime.
- `mode_search()` profiles query → builds cache key including rerank mode → cache hit or
  backend dispatch → optional rerank → output.
- `mode_read()` builds policy-aware cache key → cache hit or `read_with_fallback()` →
  robots gate → requested reader/fallback chain → full markdown cache → presentation
  truncation.
- `cache.get()` validates JSON/schema/TTL → marks recency best-effort → returns data;
  `cache.set()` atomically replaces file → evicts only while an enabled budget is
  exceeded.

### Error and failure propagation

- Corrupt, expired, or schema-stale entries remain misses; stale schema/TTL entries are
  removed best-effort.
- `os.utime` and eviction filesystem errors remain non-fatal.
- Invalid LLM JSON or invalid field types fall back to deterministic values and never
  reach `.strip()` on non-strings.
- Existing `URLError` handling and backend fallback behavior remain unchanged.

### State lifecycle risks

- Cache access changes only file metadata, not entry data, schema, timestamp, or TTL.
- Separate robots keys intentionally leave prior bypassed entries on disk until normal
  eviction; they cannot satisfy a respecting request.
- Settings are reset per invocation from environment; direct module-level assignments
  are no longer treated as durable CLI configuration.

### API surface parity

- CLI flags and public Python entry points remain backward compatible.
- No new dependency, engine, command, output schema, or cache schema bump is required.
- `--zai-timeout` retains its current name and behavior; global timeout unification is
  explicitly deferred.

## Implementation Phases

### Phase 1: Regression tests

- Add failing tests for byte-only cache limits, disabled limits, hit-based recency, and
  non-fatal `utime` failure.
- Set cache mtimes explicitly with `os.utime(..., ns=...)`; remove clock sleeps from
  eviction tests. Derive byte budgets from actual collected file sizes.
- Assert that a failed `json.dump`/`os.replace` does not run eviction or delete healthy
  entries, and that a recent mtime cannot revive an expired serialized TTL.
- Add cache-key isolation tests for rerank and read robots/timeout options.
- Add malformed-profile tests and repeated-invocation configuration tests.

### Phase 2: Focused corrections

- Patch cache predicates/recency and successful-write eviction.
- Patch search/read cache parameters.
- Add profile normalization and reentrant settings reload.

### Phase 3: Documentation and cleanup

- Refresh command examples and environment/cache semantics.
- Format touched files and review the complete diff for scope creep.

## Acceptance Criteria

### Functional requirements

- [x] With both cache limits disabled, writing N entries preserves N entries.
- [x] With only a byte limit enabled and sufficient budget, multiple entries remain.
- [x] Under count or byte pressure, a recently read entry survives ahead of an older
      unread entry.
- [x] A valid cache hit succeeds even if recency metadata cannot be updated.
- [x] Cache promotion does not extend serialized TTL, and failed writes do not evict
      healthy entries.
- [x] Search cache keys distinguish reranked and non-reranked results.
- [x] Read cache keys distinguish robots policy and `zai_timeout`.
- [x] Smart search/research tolerate malformed-but-valid profile JSON without raising.
- [x] Direct `expand_queries()` and `search_queries()` calls tolerate mixed/non-string
      caller data without mutation.
- [x] A second `main()` invocation without common flags does not inherit flags from the
      first and still honors environment defaults.
- [x] CLI docs match `build_parser()` for all current engines and relevant flags.

### Non-functional requirements

- [x] Zero runtime dependencies remain intact.
- [x] Vertical-slice import rules remain intact.
- [x] Existing public CLI/output contracts remain backward compatible.
- [x] Network access remains fully mocked in tests.

### Quality gates

- [x] `python3 -m pytest tests/ -q` passes.
- [x] Coverage remains at or above the configured 85% gate.
- [x] `ruff check src tests` passes.
- [x] `ruff format --check src tests` passes.
- [x] `mypy src` passes.
- [x] Narrow security/dead-code sensors report no new actionable findings in touched
      code relative to the baseline.
- [x] Final diff preserves pre-existing `.gitignore` and control-plane changes.

## Dependencies and Risks

- Touching file mtimes introduces small write I/O on cache hits; this is the simplest
  stdlib mechanism consistent with the existing file-backed design.
- `scandir` plus sorting remains O(n log n) after a write; this is acceptable under the
  default 500-entry cap and does not justify a persistent index.
- Multiprocess writers may race during best-effort eviction. Atomic replacement protects
  entry completeness, but strict cross-process LRU ordering is not promised.
- LRU tests need explicit nanosecond mtimes and deterministic path tie-breaking to remain
  stable across filesystems.
- Rebuilding settings per invocation may expose tests or embedded callers that relied
  on undocumented module-attribute leakage; this is intentional correction toward the
  documented `reload_settings()` contract.
- Profile typing must not make normal LLM output overly strict; fallback is field-local.

## Deferred Work

- Unifying `--timeout` with backend-specific explicit timeout values.
- Renaming or splitting `--zai-timeout`, which currently reaches other reader fallbacks.
- Changing robots fail-open policy or HTTP transport.
- Adding new engines, dependencies, or synthesis schemas.

## Documentation Plan

- Update `CLAUDE.md` command reference.
- Expand `README.md` usage/environment sections with current engines, policy flags, and
  cache-limit semantics.
- Record shipped behavior and validation in `.memory-bank/CONTEXT.md` and
  `.memory-bank/progress.md` after implementation.

## Sources and References

- `src/web_research/shared/cache.py`
- `src/web_research/shared/config.py`
- `src/web_research/shared/cli_helpers.py`
- `src/web_research/features/search/command.py`
- `src/web_research/features/read/command.py`
- `src/web_research/features/intelligence/engine.py`
- `src/web_research/cli_parser.py`
- `ARCHITECTURE.md`
- `.memory-bank/topics/code-architecture.md`
- `.memory-bank/REFERENCE.md`
- `.memory-bank/progress.md`
