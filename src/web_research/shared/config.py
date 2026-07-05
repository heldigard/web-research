"""Environment configuration for web-research engine."""

from __future__ import annotations

import os
from pathlib import Path

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8080").rstrip("/")
FC_URL = os.getenv("FC_URL", "http://localhost:3002").rstrip("/")
FC_API_KEY = os.getenv("FC_API_KEY", "fc-local-dev-key-2024")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL", "qwen3.5:4b"
)  # universal clean default (re-bench 2026-07-04: code_gen #3, smart_trim #14)
# Synthesis model: the FINAL cited answer the controller/user reads. Per-function
# override (re-bench 2026-07-04, Ollama 0.31.1): web_synth combined #1 =
# batiai/gemma4-e4b:q4 (5.0GB, gemma4 e4b Q4). crow:9b was the prior winner;
# now demoted to fallback. qwen3.5:4b stays for query_profile + focused_extract.
OLLAMA_SYNTH_MODEL = os.getenv("OLLAMA_SYNTH_MODEL", "batiai/gemma4-e4b:q4")
# Cloud fallback for synthesis (fires only when local crow:9b is down). A
# frontier-class ECONOMICAL model gives better CITED JUDGMENT than the
# signal-distillation ling tier on multi-source synthesis: deepseek-v4-flash
# (1M ctx, 79% SWE-bench, $0.14/$0.28) filters noise + structures the
# contradiction analysis better than ling-2.6-flash (bench 2026-06-28:
# omits irrelevant pricing/output, distinguishes config-variance vs true
# contradiction). $0.0002/call, rare path → negligible cost. No :free routes
# (user policy: paid latest economical only).
WEB_SYNTH_CLOUD_MODEL = os.getenv("WEB_SYNTH_CLOUD_MODEL", "deepseek/deepseek-v4-flash")
OLLAMA_EMBED = os.getenv(
    "OLLAMA_EMBED", "embeddinggemma"
)  # eval winner (MRR 0.724); was nomic-embed-text then qwen3-embedding:4b
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
ZAI_API_KEY = os.getenv("ZAI_API_KEY") or os.getenv("Z_AI_API_KEY", "")

TIMEOUT = int(os.getenv("WEB_RESEARCH_TIMEOUT", "30"))
VERBOSE = os.getenv("WEB_RESEARCH_VERBOSE", "") != ""

CACHE_DIR = os.getenv("WEB_RESEARCH_CACHE_DIR", "")
CACHE_TTL_SECONDS = int(os.getenv("WEB_RESEARCH_CACHE_TTL", "3600"))

# Sibling ecosystem scripts shared across the cross-CLI harness (NOT part of
# this package): ollama_client.py (embed/generate/is_alive) and cheap_llm.py
# (cloud cascade). Both are optional; the engine degrades gracefully when absent.
# Override only if your harness lives elsewhere. Defaults to ~/.claude/scripts/.
ECOSYSTEM_SCRIPTS = os.getenv("WEB_RESEARCH_SCRIPTS", str(Path.home() / ".claude" / "scripts"))
