# Active Context
> Session handoff — keep short. Depth lives in progress.md / topics/.

## Status (2026-07-18)
- **Branch**: `main` — Ubuntu-native DDG fix + status command ready to push
- **Tests**: 144 green · ruff · pyright clean
- **Live**: SearXNG/Firecrawl/Ollama OK; `search --engine duckduckgo` returns
  true `duckduckgo` sources (was silent searxng merge + captcha)

## This session shipped
- fix: DDG Accept/Referer headers + anomaly-modal detection
- fix: SearXNG fallback only for `minimax`/`zai`
- feat (prior commit): `web-research status`
- docs: CLAUDE model defaults + status; CHANGELOG; memory compact

## Do not re-do
- ollama_client / cheap_llm graduation (already shipped sibling projects)
- Re-adding SearXNG merge for free engines (masks failures)
