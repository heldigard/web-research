# Memory Index
> Project: web-research — local-first web research engine for LLM agents

## Identity
`web-research` is the engine behind the cross-CLI ecosystem's "Web" tier
(CLAUDE.md MCP priority row "Web"): skill `web-search` → this engine
(SearXNG → Firecrawl → Z.AI/MiniMax → Ollama rerank/synthesis → cloud fallback).
Graduated 2026-07-04 from `~/.claude/scripts/web_research/` (flat package).
Public repo: https://github.com/heldigard/web-research

## Read First
- CONTEXT.md: current state (graduation + cheap_llm decision)
- REFERENCE.md: CLI subcommands/flags, engine endpoints, model routing
- systemPatterns.md: vertical-slice layout, shim reconnection, ECOSYSTEM_SCRIPTS
- topics/code-architecture.md: package map
- progress.md: migration milestone

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
