---
status: complete
priority: p3
issue_id: "001"
tags: [code-review, agent-native, cli, capabilities]
dependencies: []
---

# Expose command options in the capability manifest

## Problem Statement

`web-research capabilities` exposes command names, engines, cost, and broad JSON support,
but not agent-selectable policies and options such as robots enforcement, `--no-cache`,
reader timeouts, or `research --code-analyze`. Routers that rely only on the machine-
readable contract must inspect `--help` or human documentation to discover those choices.

This is not a regression in the cache/CLI resilience change. It is a pre-existing agent-
native discoverability gap that needs an explicit schema-compatibility decision.

## Findings

- `src/web_research/capabilities.py` emits compact cards with `name`, `purpose`, safety,
  `structured_json`, `engines`, and `cost` only.
- `src/web_research/cli_parser.py` also defines robots policy, reader wait/timeout,
  structured-output flags, `--no-cache`, and local code analysis.
- The README documents these behaviors for humans, but the router contract does not.
- Existing consumers may treat `schema_version: 1` strictly; additive fields need a
  compatibility check before changing the payload.

## Proposed Solutions

### Option 1: Add compact option metadata to schema v1

**Approach:** Add optional `options`, `defaults`, and policy fields to each capability
card while preserving every existing field and value.

**Pros:**
- Backward compatible for consumers that ignore unknown fields.
- Gives routers enough data without invoking every command's help.

**Cons:**
- Strict consumers may reject additional keys despite the intended additive contract.
- Duplicates some parser metadata unless maintained carefully.

**Effort:** 1-2 hours

**Risk:** Medium

---

### Option 2: Introduce capability schema v2

**Approach:** Bump the manifest schema and define a stable per-command option structure,
then update known router consumers together.

**Pros:**
- Makes the compatibility boundary explicit.
- Allows a clean, complete contract with validation tests.

**Cons:**
- Requires coordinated consumer migration.
- More work than the immediate metadata addition.

**Effort:** 3-5 hours

**Risk:** Medium

---

### Option 3: Add a separate detailed mode

**Approach:** Keep the compact default payload and add `capabilities --detailed` for
parser-derived option metadata.

**Pros:**
- Preserves the exact compact contract.
- Routers opt into larger metadata only when needed.

**Cons:**
- Adds another CLI mode/branch and two manifests to maintain.
- Routers still need to know to request detail.

**Effort:** 2-4 hours

**Risk:** Low

## Recommended Action

Implemented Option 1: optional per-command `options` metadata in schema v1.
No strict in-tree capability-manifest consumer exists, and every pre-existing
field and value remains unchanged. A strict external validator must use an
explicit schema-v2 migration before it can require an exact key set.

## Technical Details

**Affected files:**

- `src/web_research/capabilities.py`
- `src/web_research/cli_parser.py`
- `tests/test_web_research.py`
- Router documentation/consumers discovered during compatibility audit

**Database changes:** None.

## Resources

- Review source: agent-native review of the 2026-07-12 cache/CLI resilience diff.
- Current human contract: `README.md` and `CLAUDE.md`.

## Acceptance Criteria

- [x] Known in-tree router consumers and their schema strictness are identified.
- [x] Chosen schema/versioning strategy is documented.
- [x] Machine-readable metadata exposes robots policy, cache bypass, structured-output
      flags, reader timeouts/wait, and local code analysis where applicable.
- [x] Existing capability fields remain compatible.
- [x] Capability payload tests cover every parser subcommand and engine list.
- [x] README/CLAUDE references remain accurate because the command and compact
      machine-readable contract are unchanged; `options` is additive detail.

## Work Log

### 2026-07-12 - Initial discovery

**By:** Codex

**Actions:**

- Compared `capabilities.py`, parser flags, and current human documentation.
- Classified the gap as P3 because all CLI actions remain directly agent-invokable and
  no current behavior is broken.
- Deferred implementation pending an explicit schema-compatibility check.

**Learnings:**

- Engine parity is already correct; the gap is option/policy discoverability.
- Schema compatibility, not implementation complexity, is the deciding risk.

### 2026-07-12 - Resolution

**By:** Codex

**Actions:**

- Verified that no in-tree router consumes `capabilities_payload()` or validates
  the manifest beyond the existing contract test.
- Preserved `schema_version: 1` and every existing capability field/value.
- Added compact `options` metadata and exact payload/engine-parity checks.

**Decision:**

- This is an additive schema-v1 change. Any external strict validator that
  rejects unknown keys requires an explicit schema-v2 rollout.

## Notes

- Do not fold this into unrelated cache or settings changes.
