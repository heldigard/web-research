# Memory Index
> Project: web-research — local-first web research engine for LLM agents

## Identity
Engine behind the cross-CLI "Web" tier: skill `web-search` → this package
(SearXNG → Firecrawl → Z.AI/MiniMax → Ollama rerank/synthesis → cloud fallback).
Graduated 2026-07-04 from `~/.claude/scripts/web_research/`.
Public: https://github.com/heldigard/web-research

## Read First
- `CONTEXT.md` — current state / last ship
- `REFERENCE.md` — CLI, env, model defaults
- `systemPatterns.md` — HttpClient, backends, cache schema
- Repo `ARCHITECTURE.md` — add-backend recipes
- `topics/code-architecture.md` — package map + data flow
- `progress.md` — milestone log (compact)

## Update Rules
- Decision → `systemPatterns.md` (+ graph if relational)
- Task done → `progress.md` (short) · handoff → `activeContext.md`
- Failed approach → `dead-ends.md`
- Deep context → `topics/<slug>.md`

## Siblings
`codeq`, `smart-trim`, `prompt-improve`, `ollama-client`, `cheap-llm` —
same graduation pattern under `github.com/heldigard/<name>`.
