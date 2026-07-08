# Ecosystem improvement proposals — ranked

> Derived from `ECOSYSTEM.md`. Each proposal states value, risk, effort, and
> the repos it touches. Verified against source 2026-07-08.

## P1 — Graduate `ollama_client` to `~/ollama-client/` (HIGH value)

**Problem**: `ollama_client.py` is a 756-line flat script in `~/.claude/scripts/`
consumed by **four** projects (`codeq`, `smart-trim`, `prompt-improve`,
`web-research`), each with its own `sys.path` bootstrap. `cheap_llm` already
graduated to `~/cheap-llm/` with SemVer; `ollama_client` did not — the
ecosystem's biggest asymmetry.

**Change**: extract `~/ollama-client/` (vertical-slice package, mirroring
web-research/codeq), keep a `~/.claude/scripts/ollama_client.py` **shim** that
re-exports from the project (zero edits to consumers short-term), add SemVer
`require()`. Consumers migrate to `import ollama_client` as a real package.

**Value**: one source of truth for Ollama HTTP; version-gated contract; the 4
`compat.py` bootstraps collapse to a normal dependency.
**Risk**: medium — touches 4 repos + the harness script. Mitigated by the shim
(preserves the `import ollama_client` surface).
**Effort**: ~1 session (move + pyproject + shim + smoke each consumer).

## P2 — Shared model registry (MEDIUM value, LOW risk)

**Problem**: 7+ hardcoded model defaults diverge across 5 projects (table in
`ECOSYSTEM.md`). Rebenching one model means hunting defaults in every repo.

**Change**: a single `~/.config/web-research-harness/models.toml` (or
`~/.claude/scripts/model_registry.py`) exporting canonical defaults; each
project reads it with fallback to its current hardcoded value (non-breaking).

**Value**: coordinated model swaps in one file; no project breaks if the file
is absent.
**Risk**: low — opt-in read, fallback preserves current behavior.
**Effort**: ~0.5 session (registry module + wire into 5 configs).

## P3 — Shared LLM-response cache (MEDIUM value, MEDIUM risk)

**Problem**: `web-research` caches search/read at `~/.cache/web-research/`;
`cheap-llm` caches generations at `~/.claude/state/cheap-llm-cache/`. The same
(prompt, model, params) can be re-computed across projects.

**Change**: one keyed cache dir (`~/.cache/harness-llm/`) keyed by
`sha256(model|temperature|prompt)`, consumed by `ollama_client.generate` and
`cheap_llm.complete` directly (so every project benefits transitively).

**Value**: cuts duplicate local-LLM calls (codeq summaries, web-research
synthesis, prompt-improve rewrites).
**Risk**: medium — cache invalidation on model swap; needs the `engine_tag`
pattern web-research already uses.
**Effort**: ~1 session (centralize in `ollama_client` after P1 graduates it).

## P4 — web-research ↔ codeq integration (MEDIUM value, LOW risk)

**Problem**: web-research scrapes API docs / library READMEs but has no
code-fact extraction; `focused_extract` treats code as prose.

**Change**: opt-in `research --code-analyze` flag that, for pages containing
fenced code, shells out to `codeq body/sig` on detected symbols before
synthesis. Graceful-degrade if `codeq` is absent.

**Value**: sharper synthesis for technical queries (signatures, call sites).
**Risk**: low — opt-in subprocess, no hard dependency.
**Effort**: ~0.5 session (detection + subprocess + wire into `_build_docs`).

## P5 — Unified `harness_path` helper (LOW value, LOW risk)

**Problem**: three projects duplicate the `sys.path.insert(~/.claude/scripts)`
bootstrap in their `compat.py`.

**Change**: one `~/.claude/scripts/harness_path.py` with
`add_harness_to_path()`; each `compat.py` calls it.

**Value**: collapses 3 duplicates; one fix if the harness moves.
**Risk**: low. **Effort**: ~0.25 session. (Largely subsumed by P1.)

---

## Recommended order

1. **P1** (graduate `ollama_client`) — unblocks P3 and removes the root coupling smell.
2. **P2** (model registry) — quick win, immediately useful, zero breakage.
3. **P4** (codeq integration) — visible feature win for web-research specifically.
4. **P3** then **P5** — follow-on cleanups once P1 lands.

P1, P2, P3, P5 are cross-repo (touch `~/codeq`, `~/smart-trim`,
`~/prompt-improve`, `~/cheap-llm`, `~/.claude/scripts`). They should land as
coordinated commits per repo, preserving each repo's style. Confirm scope
before starting.
