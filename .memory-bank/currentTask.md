# Current Task
> Updated: 2026-07-08

## Goal
None active. Zero-dependency enhancement batch shipped (11 changes, 93 tests
green — see `progress.md` 2026-07-08 entry and `CHANGELOG.md`).

## Next likely work
- cheap_llm.py graduation (separate future project — 33KB, 8+ consumers).
- Live-model re-bench if OLLAMA_SYNTH_MODEL / OLLAMA_EMBED change.
- Optional: ship `httpx` HttpClient impl behind a feature flag (supersedes
  the stdlib retry loop with pooling + async).
- Optional: `ragas`/`promptfoo` eval suite to regression-test retrieval quality.
- Optional: TEI rerank live smoke once a TEI server is stood up locally.
