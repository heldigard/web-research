"""Typed configuration loaded from environment.

Single source of truth for every runtime knob. Modules read attributes from
:func:`get_settings` instead of poking at module-level globals, which makes
the package testable (reload settings per-test) and version-aware (cache
keys, log tags, telemetry).

Use :func:`reload_settings` to re-read env after a CLI override
(``--timeout`` / ``--verbose``) — the fields that the CLI can influence
are mutated on the singleton; the rest are reset from the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace  # noqa: F401 — replace kept for legacy callers
from pathlib import Path
from typing import TYPE_CHECKING


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


# Default-model notes are kept inline (not broken out into separate constants)
# because they document a single-bench decision recorded in MEMORY.md.
_OLLAMA_DEFAULT_MODEL = "cryptidbleh/gemma4-claude-opus-4.6:latest"
_OLLAMA_DEFAULT_SYNTH_MODEL = "hf.co/TeichAI/Qwen3.5-9B-Fable-5-v1-GGUF:Q4_K_M"  # web_synth combined #1, 2026-07-09 validation
_OLLAMA_DEFAULT_SYNTH_FALLBACK_MODEL = "xentriom/gemma-4-12B-agentic-fable5-composer2.5-v2:Q8_0"  # web_synth FALLBACK (12GB VRAM); for VRAM-tight hosts set OLLAMA_SYNTH_FALLBACK_MODEL=cryptidbleh/gemma4-claude-opus-4.6:latest
_OLLAMA_DEFAULT_EMBED = "embeddinggemma"  # MRR 0.724 eval winner
_WEB_SYNTH_DEFAULT_CLOUD = "deepseek/deepseek-v4-flash"


# Bump when a config field, prompt template, or backend behavior changes
# in a way that makes existing on-disk cache entries stale. Cache entries
# stamped with a prior version are invalidated automatically.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings. Constructed via :func:`load_settings`."""

    # Self-hosted service endpoints
    searxng_url: str = "http://localhost:8080"
    firecrawl_url: str = "http://localhost:3002"
    firecrawl_api_key: str = "fc-local-dev-key-2024"  # local default; override in prod
    ollama_url: str = "http://localhost:11434"

    # Ollama model assignments
    ollama_model: str = _OLLAMA_DEFAULT_MODEL
    ollama_synth_model: str = _OLLAMA_DEFAULT_SYNTH_MODEL
    ollama_synth_fallback_model: str = _OLLAMA_DEFAULT_SYNTH_FALLBACK_MODEL
    ollama_embed: str = _OLLAMA_DEFAULT_EMBED

    # Direct API integrations — endpoints externalized so proxies / on-prem
    # forks can repoint without code edits.
    minimax_api_key: str = ""
    minimax_url: str = "https://api.minimax.io/v1/coding_plan/search"
    zai_api_key: str = ""
    zai_search_url: str = "https://api.z.ai/api/paas/v4/web_search"
    zai_reader_url: str = "https://api.z.ai/api/paas/v4/reader"

    # Cloud synthesis fallback
    web_synth_cloud_model: str = _WEB_SYNTH_DEFAULT_CLOUD

    # Optional stage-2 cross-encoder rerank via a self-hosted TEI server
    # (HuggingFace Text Embeddings Inference, /rerank endpoint). Empty string
    # disables it and the engine falls back to the bi-encoder cosine ranker.
    tei_rerank_url: str = ""

    # HTTP / runtime
    timeout: int = 30
    verbose: bool = False
    # Retry transient HTTP failures (429 / 5xx / URLError) with exponential
    # backoff. Defaults are tiny so injected-failure tests stay fast; tune up
    # for production. Set http_max_retries=0 to disable entirely.
    http_max_retries: int = 2
    http_backoff_base: float = 0.2

    # Cache
    cache_dir: str = ""  # empty → ~/.cache/web-research
    cache_ttl_seconds: int = 3600
    # Size-bound LRU eviction (runs on every ``set``). 0 disables the limit.
    cache_max_entries: int = 500
    cache_max_bytes: int = 50_000_000  # 50 MB

    # Synthesis budget — hard cap for source text sent to the final model
    web_synth_max_context_chars: int = 14000

    # Sibling harness scripts (ollama_client.py, cheap_llm.py) — see compat.py
    ecosystem_scripts: str = ""

    # Schema version for cache invalidation (increment on breaking changes)
    schema_version: int = SCHEMA_VERSION


def load_settings() -> Settings:
    """Resolve settings from environment. Returns a new frozen instance."""
    return Settings(
        searxng_url=_env_str("SEARXNG_URL", "http://localhost:8080").rstrip("/"),
        firecrawl_url=_env_str("FC_URL", "http://localhost:3002").rstrip("/"),
        firecrawl_api_key=_env_str("FC_API_KEY", Settings.firecrawl_api_key),
        ollama_url=_env_str("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=_env_str("OLLAMA_MODEL", _OLLAMA_DEFAULT_MODEL),
        ollama_synth_model=_env_str("OLLAMA_SYNTH_MODEL", _OLLAMA_DEFAULT_SYNTH_MODEL),
        ollama_synth_fallback_model=_env_str(
            "OLLAMA_SYNTH_FALLBACK_MODEL", _OLLAMA_DEFAULT_SYNTH_FALLBACK_MODEL
        ),
        ollama_embed=_env_str("OLLAMA_EMBED", _OLLAMA_DEFAULT_EMBED),
        minimax_api_key=_env_str("MINIMAX_API_KEY", ""),
        minimax_url=_env_str("MINIMAX_URL", Settings.minimax_url).rstrip("/"),
        zai_api_key=_env_str("ZAI_API_KEY") or _env_str("Z_AI_API_KEY", ""),
        zai_search_url=_env_str("ZAI_SEARCH_URL", Settings.zai_search_url).rstrip("/"),
        zai_reader_url=_env_str("ZAI_READER_URL", Settings.zai_reader_url).rstrip("/"),
        web_synth_cloud_model=_env_str("WEB_SYNTH_CLOUD_MODEL", _WEB_SYNTH_DEFAULT_CLOUD),
        tei_rerank_url=_env_str("TEI_RERANK_URL", "").rstrip("/"),
        timeout=_env_int("WEB_RESEARCH_TIMEOUT", 30),
        verbose=_env_bool("WEB_RESEARCH_VERBOSE", False),
        http_max_retries=_env_int("WEB_RESEARCH_HTTP_RETRIES", Settings.http_max_retries),
        http_backoff_base=_env_float("WEB_RESEARCH_HTTP_BACKOFF", Settings.http_backoff_base),
        cache_dir=_env_str("WEB_RESEARCH_CACHE_DIR", ""),
        cache_ttl_seconds=_env_int("WEB_RESEARCH_CACHE_TTL", 3600),
        cache_max_entries=_env_int("WEB_RESEARCH_CACHE_MAX_ENTRIES", Settings.cache_max_entries),
        cache_max_bytes=_env_int("WEB_RESEARCH_CACHE_MAX_BYTES", Settings.cache_max_bytes),
        web_synth_max_context_chars=_env_int("WEB_SYNTH_MAX_CONTEXT_CHARS", 14000),
        # ECOSYSTEM_SCRIPTS must hold BOTH ollama_client.py and the cheap_llm.py
        # shim (~/.claude/scripts). Do NOT fall back to CHEAP_LLM_HOME — that
        # points at the cheap-llm PROJECT ROOT, which has cheap_llm.py but NOT
        # ollama_client.py, breaking the ollama_client import in compat.py.
        # The shim resolves CHEAP_LLM_HOME internally to find the real module.
        ecosystem_scripts=(
            _env_str("WEB_RESEARCH_SCRIPTS") or str(Path.home() / ".claude" / "scripts")
        ),
        schema_version=SCHEMA_VERSION,
    )


# Module-level singleton — replaced via reload_settings() when CLI flags
# override env values (timeout, verbose). Frozen dataclass: setters mutate
# the singleton via ``replace``.
_settings: Settings = load_settings()


def get_settings() -> Settings:
    """Return the current settings singleton."""
    return _settings


def reload_settings(**overrides: object) -> Settings:
    """Re-resolve from env, optionally overriding fields.

    Used by ``cli_helpers.apply_common`` to push ``--timeout`` / ``--verbose``
    flags into the runtime settings without touching module globals. Also
    clears any stale legacy ``__dict__`` cache (e.g. from earlier tests that
    wrote ``config.TIMEOUT = 99`` directly) so the proxy reads through to
    the new singleton.
    """
    global _settings
    fresh = load_settings()
    if overrides:
        fresh = replace(fresh, **overrides)  # type: ignore[arg-type]
    _settings = fresh
    for name in (*_LEGACY_NAME_MAP.keys(), *_MODERN_ATTRS):
        globals().pop(name, None)
    return _settings


# -- Back-compat shims -----------------------------------------------------
# Legacy SCREAMING_CASE names (``config.MINIMAX_API_KEY``, ``config.TIMEOUT``)
# are imported by the rest of the package and used by tests that do
# ``patch.object(wr.search, "MINIMAX_API_KEY", ...)``. Read-only proxy:
# modern code should use ``settings.x`` or ``get_settings().x``.
#
# Writes via ``config.X = Y`` go to module ``__dict__`` directly (Python does
# not invoke module ``__setattr__`` for normal assignments). To mutate
# settings, call :func:`reload_settings` instead.

_LEGACY_NAME_MAP: dict[str, str] = {
    "SEARXNG_URL": "searxng_url",
    "FC_URL": "firecrawl_url",
    "FC_API_KEY": "firecrawl_api_key",
    "OLLAMA_URL": "ollama_url",
    "OLLAMA_MODEL": "ollama_model",
    "OLLAMA_SYNTH_MODEL": "ollama_synth_model",
    "OLLAMA_SYNTH_FALLBACK_MODEL": "ollama_synth_fallback_model",
    "OLLAMA_EMBED": "ollama_embed",
    "MINIMAX_API_KEY": "minimax_api_key",
    "ZAI_API_KEY": "zai_api_key",
    "TIMEOUT": "timeout",
    "VERBOSE": "verbose",
    "CACHE_DIR": "cache_dir",
    "CACHE_TTL_SECONDS": "cache_ttl_seconds",
    "WEB_SYNTH_CLOUD_MODEL": "web_synth_cloud_model",
    "WEB_SYNTH_MAX_CONTEXT_CHARS": "web_synth_max_context_chars",
    "ECOSYSTEM_SCRIPTS": "ecosystem_scripts",
}
_MODERN_ATTRS = set(Settings.__dataclass_fields__.keys())


def __getattr__(name: str) -> object:
    if name == "_settings":
        return _settings
    if name in _LEGACY_NAME_MAP:
        return getattr(_settings, _LEGACY_NAME_MAP[name])
    if name in _MODERN_ATTRS:
        return getattr(_settings, name)
    raise AttributeError(f"module 'web_research.shared.config' has no attribute {name!r}")


# Type stubs for mypy / pyright — these names are resolved at runtime via
# ``__getattr__`` above but need static typing for downstream modules that
# import them as ``from .config import MINIMAX_API_KEY``.
if TYPE_CHECKING:
    SEARXNG_URL: str
    FC_URL: str
    FC_API_KEY: str
    OLLAMA_URL: str
    OLLAMA_MODEL: str
    OLLAMA_SYNTH_MODEL: str
    OLLAMA_SYNTH_FALLBACK_MODEL: str
    OLLAMA_EMBED: str
    MINIMAX_API_KEY: str
    ZAI_API_KEY: str
    TIMEOUT: int
    VERBOSE: bool
    CACHE_DIR: str
    CACHE_TTL_SECONDS: int
    WEB_SYNTH_CLOUD_MODEL: str
    WEB_SYNTH_MAX_CONTEXT_CHARS: int
    ECOSYSTEM_SCRIPTS: str
