# Project and ecosystem hardening plan

> Date: 2026-07-23
> Status: validated / complete
> Scope: `web-research` plus the directly coupled local Web-tier skills

## Objective

Improve correctness, bounded network behavior, packaging/CI reliability, and
the accuracy of the surrounding agent-facing configuration without changing
the CLI contract or enabling paid services implicitly.

## Baseline evidence

- The working tree started clean except for one pre-existing line in
  `.memory-bank/progress.md`; it must be preserved.
- `pytest`: 182 passing tests, 89.51% coverage (gate: 85%).
- `ruff check`: clean.
- `ruff format --check .`: fails on 12 test files, so the current CI format
  step is red on `main`.
- Tests default to the user's real cache directory, which is unsafe for local
  runs and allows cross-process contamination.
- `codescan`: no secret, SAST, lint, type, or architecture findings; four
  vulture findings are pytest class-name false positives.
- The project declares Python 3.11–3.13 support but CI only exercises 3.12;
  the active Python 3.14 interpreter also passes the baseline suite.
- Wheel and sdist build successfully. The sdist unnecessarily contains
  `.memory-bank/`, `todos/`, and repository-only agent coordination material.
- `robots.txt` is fetched through `RobotFileParser.read()` without the
  configured HTTP timeout, retries, or project user agent.
- `Retry-After` accepts negative/non-finite numeric values, which can reach
  `time.sleep()` as invalid delay values.
- Directly coupled Web-tier skill docs omit the stdlib HTML fallback,
  DuckDuckGo in some engine lists, and the explicit PAYG opt-in boundary.

## Proposed change set

### 1. Runtime correctness

- Reject negative and non-finite `Retry-After` delays while retaining the
  existing cap.
- Fetch `robots.txt` through the shared bounded HTTP client, preserving
  `RobotFileParser`'s 401/403 deny and 4xx allow semantics.
- Reject non-HTTP(S) URLs at the robots boundary.
- Add focused regression tests for timeout propagation, parsing, HTTP status
  behavior, and invalid retry delays.

### 2. CI and packaging

- Format the existing test suite so the checked-in tree satisfies the current
  CI format command.
- Give every pytest process a unique temporary cache and clean it at exit.
- Declare the already-passing Python 3.14 line and exercise every declared
  version (3.11–3.14) in CI while keeping lint/type/build checks on one
  version for fast feedback.
- Make the test toolchain reproducible from `pyproject.toml`/`uv.lock` instead
  of installing mypy as an untracked second step.
- Add least-privilege workflow permissions, cancellation of superseded runs,
  a timeout, and a package build/smoke check.
- Exclude agent memory, plans, and completed TODO records from source
  distributions while retaining tests and user-facing documentation.
- Add standard project URLs to built package metadata.

### 3. Direct ecosystem configuration

- Align `web-search`, `web-research`, `search-smart`, `searxng`, and
  `web-reader` skill docs with the live capability manifest.
- Keep free→paid escalation and cloud synthesis wording explicit: subscription
  search engines may be used only when configured, and PAYG synthesis still
  requires `--allow-cloud-fallback`.
- Avoid changing unrelated skills, model defaults, credentials, or sibling
  repositories.

### 4. Documentation and durable context

- Add concise Unreleased changelog notes for runtime/CI/packaging changes.
- Record only the shipped durable facts in `.memory-bank/`; do not copy logs
  or session transcripts.

## Acceptance criteria

- All targeted regression tests pass.
- Full pytest suite passes with coverage at or above 85%.
- `ruff check .` and `ruff format --check .` pass.
- mypy and `codescan all` report no errors.
- Wheel and sdist build; the wheel imports and runs `--version`; the sdist
  excludes internal agent-state paths.
- Python 3.11–3.14 each pass the test suite locally.
- The final diff contains no unrelated edits and preserves the pre-existing
  memory-bank change.

## Implementation map

| Slice | Files | Invariants |
|---|---|---|
| HTTP delay validation | `src/web_research/shared/http.py`, `tests/test_enhancements.py` | Valid positive delays and the 30-second cap remain unchanged; malformed values fall back to exponential backoff. |
| Bounded robots fetch | `src/web_research/shared/robots.py`, `tests/test_enhancements.py` | Cache TTL and fail-open network policy remain; 401/403 remain deny-all; ordinary 4xx remain allow-all. |
| Toolchain metadata | `pyproject.toml`, `uv.lock` | Runtime stays zero-dependency; additions are test/build-only. |
| CI | `.github/workflows/ci.yml` | No secrets or external services are required; network calls stay mocked in tests. |
| Source distribution | `pyproject.toml` | Wheel contents remain unchanged; README, license, architecture, changelog, and tests remain in sdist. |
| Skill contract | five `~/.claude/skills/*/SKILL.md` files | Commands must match `web-research capabilities`; no implicit PAYG authorization. |
| Release notes/context | `CHANGELOG.md`, `.memory-bank/*` | Only current durable facts; no version bump or release claim. |

## Execution order

1. Add runtime regression tests that demonstrate the invalid-delay and
   unbounded-robots gaps.
2. Implement the smallest shared HTTP/robots changes and run their focused
   tests.
3. Update test/build dependencies and lockfile, then harden CI and sdist
   selection.
4. Apply Ruff formatting to tests (mechanical only) and verify the repository
   format gate.
5. Correct the directly coupled skill documentation against the capability
   manifest.
6. Self-review the complete diff; run the full multi-version and static
   validation matrix; resolve any findings.
7. Update changelog and memory with results that were actually verified.

## Risk analysis and mitigations

- **Robots status semantics:** replacing `RobotFileParser.read()` could
  accidentally turn 403 into fail-open. Mitigation: encode 401/403 and generic
  4xx behavior explicitly and cover both with tests.
- **Retry timing tests:** retries can make failure tests slow. Mitigation:
  existing tests set backoff to zero; focused tests inject a fake client or
  patched `urlopen`.
- **Python-version drift:** local 3.11–3.14 interpreters are available through
  uv, but the active `.venv` is 3.14. Mitigation: create isolated temporary uv
  environments/caches and run the same suite on each declared version.
- **External skill edits are outside this Git worktree:** they will not appear
  in `git diff`. Mitigation: save before/after unified diffs separately and
  smoke the actual wired commands after edits.
- **Broad formatter churn:** only files Ruff already reports will change, with
  no semantic rewrite. Review their diff independently.
- **Lockfile churn:** use `uv lock` after the narrow test-extra change and
  inspect the package delta before accepting it.

## Validation commands

```bash
pytest tests/test_enhancements.py -q
pytest --cov=web_research --cov-fail-under=85 --cov-report=term-missing
ruff check .
ruff format --check .
mypy src/
codescan all -p . --offline --json --summary-only --fail-on errors
uv build
python -m web_research --version
```

For Python 3.11–3.14, use uv-managed interpreters and isolated temporary
environments so the repository `.venv` and user configuration are not
mutated by the compatibility check.

## Validation result

- Python 3.11, 3.12, 3.13, and 3.14: 186 tests passed on each interpreter,
  including simultaneous isolated runs.
- Coverage: 89.61% (required minimum: 85%).
- Ruff format/lint, mypy, lockfile check, and `git diff --check`: clean.
- `codescan all --offline`: zero secrets, lint/type/architecture errors, or
  new actionable findings; four known pytest-class vulture false positives.
- Wheel and sdist built from isolation; the installed wheel passed version and
  capability smokes, packaged ranking data was present, and internal
  agent-state paths were absent from the sdist.
- Wired shim, PATH entry point, and five updated skill frontmatters/contracts
  passed local smoke checks. Browser/video validation was not applicable to
  this headless CLI/configuration change.

## Explicit non-goals

- No new search/reader backend, dependency-heavy HTTP rewrite, model change,
  release, commit, push, PR, deployment, or outbound publication.
- No browser/video artifact: this is a headless CLI/configuration hardening
  change with no browser flow or authorized PR target.
