# Ecosystem coupling map — web-research ↔ graduated cross-CLI projects

> Single source of truth for how `web-research` couples to the other
> "graduated" projects and the shared harness scripts. Researched 2026-07-08
> (read-only recon; claims verified against source).

## The graduated projects

| Project | Location | Entry point | Role |
|---------|----------|-------------|------|
| `codeq` | `~/codeq/` | `codeq` CLI (`codeq.cli:main`) | Code-fact navigation (ctags + ast-grep) |
| `smart-trim` | `~/smart-trim/` | `~/.claude/hooks/smart-trim.py` | PreCompact context summarizer |
| `prompt-improve` | `~/prompt-improve/` | `~/.claude/hooks/prompt-improve.py` | User-prompt rewriter |
| `cheap-llm` | `~/cheap-llm/` | `cheap-llm` CLI (`cheap_llm:main`) | Local-Ollama → cloud LLM cascade |
| `web-research` | `~/web-research/` | `web-research` CLI + shim | Web research engine (this project) |

## Shared infrastructure (the coupling surface)

```
~/.claude/scripts/
├── ollama_client.py     ← FLAT SCRIPT (NOT graduated). embed/generate/is_alive.
└── cheap_llm.py         ← SHIM → re-exports ~/cheap-llm/ (graduated, SemVer).
```

- **`ollama_client.py`** is consumed by **all four** hook/CLI projects
  (`codeq/shared/llm.py`, `smart-trim/shared/compat.py`,
  `prompt-improve/shared/compat.py`, `web-research/shared/compat.py`).
  Each does its own `sys.path.insert(0, ~/.claude/scripts)` bootstrap.
- **`cheap_llm`** is consumed by `smart-trim`, `prompt-improve`, `web-research`
  via their `compat.py`. `web-research` gates it with `cheap_llm.require("1.1")`.
- **Cache dirs are siloed**: web-research `~/.cache/web-research/`,
  cheap-llm `~/.claude/state/cheap-llm-cache/`. No shared LLM-response cache →
  the same prompt+model can be re-computed across projects.

## Model-default divergence (no single source of truth)

| Var | Project | Default |
|-----|---------|---------|
| `CODEQ_SUMMARY_MODEL` | codeq | `batiai/gemma4-e4b:q4` |
| `OLLAMA_MODEL` | web-research | `cryptidbleh/gemma4-claude-opus-4.6` |
| `OLLAMA_SYNTH_MODEL` | web-research | `hf.co/TeichAI/Qwen3.5-9B-Fable-5-v1-GGUF:Q4_K_M` |
| `OLLAMA_EMBED` | web-research | `embeddinggemma` |
| `WEB_SYNTH_CLOUD_MODEL` | web-research | `deepseek/deepseek-v4-flash` |
| `CHEAP_LLM_LOCAL_MODEL` | cheap-llm | `qwen3.5:4b` |
| `OLLAMA_MODEL_CANDIDATES` | prompt-improve | `[SetneufPT/Qwopus3.5…, qwen3.5:4b]` |

## web-research's consumer contract (what this project guarantees)

`web_research/shared/compat.py` is the **only** import boundary to the harness.
It:
1. Injects `ECOSYSTEM_SCRIPTS` (env `WEB_RESEARCH_SCRIPTS`, default
   `~/.claude/scripts/`) onto `sys.path` exactly once.
2. Imports `ollama_client as oc` and `cheap_complete` **optionally** — both
   degrade to `None` when the harness is absent, so the package imports and
   the cache/HTTP layers work without Ollama/cloud.
3. Version-gates `cheap_llm` with `require("1.1")` (fail-fast on drift).

This makes web-research a **well-behaved consumer**: it never hard-imports the
harness at module top-level outside `compat.py`, and every feature checks
`oc is None` / `cheap_complete is None` before use.

## Integration opportunities (prioritized)

See `proposals.md` (same dir) for the ranked, scoped plan with effort/risk.
