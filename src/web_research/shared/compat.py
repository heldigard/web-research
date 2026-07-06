"""Sys.path bootstrap + graceful imports of harness helpers.

Mirrors smart-trim's ``shared/compat.py`` pattern. Imported by
``web_research/__init__.py`` so the bootstrap runs exactly once on
package import, before any feature module tries to consume these helpers.

The harness helpers ``ollama_client`` and ``cheap_llm`` live under
``~/.claude/scripts/`` (resolved via ``ECOSYSTEM_SCRIPTS`` from config,
which respects the ``WEB_RESEARCH_SCRIPTS`` env var) and are NOT on
``sys.path`` by default. This module injects them and exposes the optional
imports so every consumer gets consistent names with graceful ``None``
degradation when the harness is absent.
"""

# pyright: reportMissingImports=false
# The harness helpers below live under ~/.claude/scripts/ and are
# added to sys.path at runtime by this module — Pyright cannot see them
# statically, so suppress the import-resolution diagnostics (they are
# intentionally optional, guarded by try/except).
from __future__ import annotations

import sys
from pathlib import Path

from .config import ECOSYSTEM_SCRIPTS

# Inject the harness scripts dir exactly once.
_scripts = str(ECOSYSTEM_SCRIPTS)
if _scripts and Path(_scripts).is_dir() and _scripts not in sys.path:
    sys.path.insert(0, _scripts)

# ---------------------------------------------------------------
# Optional harness helpers — degrade gracefully when absent.
# ---------------------------------------------------------------

try:
    import ollama_client as oc  # embed, generate, is_alive
except Exception:  # pragma: no cover — env-dependent
    oc = None  # type: ignore[assignment]

# Contract floor this consumer needs (cheap_llm SemVer >= 1.1). The require()
# gate fails fast on version drift instead of a cryptic mid-run error.
_CHEAP_LLM_MIN_VERSION = "1.1"

try:
    import cheap_llm

    cheap_llm.require(_CHEAP_LLM_MIN_VERSION)
    from cheap_llm import cheap_complete  # cloud LLM cascade
except Exception:  # pragma: no cover — env-dependent
    cheap_complete = None  # type: ignore[assignment]
