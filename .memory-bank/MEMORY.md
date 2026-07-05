# Memory Index
> Project: web-research — local-first web research engine for LLM agents

## Identity
`web-research` is the engine behind the cross-CLI ecosystem's "Web" tier
(CLAUDE.md MCP priority row "Web"): skill `web-search` → this engine
(SearXNG → Firecrawl → Z.AI/MiniMax → Ollama rerank/synthesis → cloud fallback).
Graduated 2026-07-04 from `~/.claude/scripts/web_research/` (flat package).
Public repo: https://github.com/heldigard/web-research

## Read First
- CONTEXT.md: current state (architecture refactor shipped 2026-07-05)
- REFERENCE.md: CLI flags, env vars (incl. URL externalization), model routing
- systemPatterns.md: HttpClient port, backend protocol, schema-versioned cache
- ARCHITECTURE.md (repo root): vertical-slice layout, recipes for new backends
- topics/code-architecture.md: package map + data flow per subcommand
- progress.md: 2026-07-04 graduation + 2026-07-05 refactor milestones

## Update Rules
- Decision -> systemPatterns.md
- Task done -> progress.md
- Failed approach -> dead-ends.md
- "Recuerda" -> activeContext.md
- Deep context -> topics/<slug>.md

## Sibling projects (same graduation pattern)
`codeq`, `smart-trim`, `prompt-improve`, `cli-orchestration` — all under
`github.com/heldigard/<name>`, all graduated from `~/.claude/scripts/` into
vertical-slice packages with their own memory bank + repo.
