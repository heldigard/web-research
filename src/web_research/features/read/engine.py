"""Read dispatcher: backend resolution + Firecrawl→Z.AI fallback.

Backend-specific HTTP lives in ``backends/<name>.py``. This module is the
thin glue: pick a reader from the registry, try the requested one first,
fall back through the chain when one returns empty markdown.
"""

from __future__ import annotations

from web_research.shared.config import ZAI_API_KEY, get_settings
from web_research.shared.http import debug

from . import backends  # noqa: F401 — re-exported so ``wr.reader.backends.<x>`` works
from .backends import FirecrawlReader, ZaiReader, build_reader


def _fallback_chain(engine: str) -> list[str]:
    """Resolve the engine to try in order: requested → Firecrawl → Z.AI (if keyed)."""
    chain = [engine]
    if engine != "firecrawl":
        chain.append("firecrawl")
    if "zai" not in chain and ZAI_API_KEY:
        chain.append("zai")
    return chain


def read_with_fallback(
    url: str,
    *,
    engine: str = "firecrawl",
    wait: int = 0,
    zai_timeout: int = 20,
) -> str:
    """Try the requested engine, then Firecrawl, then Z.AI if a key is set."""
    for eng in _fallback_chain(engine):
        reader = build_reader(eng)
        if reader is None:
            continue
        debug("reader", f"trying {eng} for {url}")
        md = (
            reader.read(url, wait=wait, timeout=zai_timeout)
            if eng == "firecrawl"
            else reader.read(url, timeout=zai_timeout)
        )
        if md:
            return md
    return ""


def scrape_with_fallback(target_url: str, wait: int = 0) -> str:
    """Backward-compatible entry used by ``mode_research``."""
    debug("reader", f"scraping {target_url}")
    return read_with_fallback(target_url, wait=wait)


# -- Legacy thin functions re-exported for the historic flat API --------------
# These exist so ``from web_research.features.read.engine import
# firecrawl_scrape`` keeps working. New code should use ``FirecrawlReader``
# from ``backends/firecrawl.py`` directly.


def firecrawl_scrape(target_url: str, wait: int = 0, timeout: int = 45) -> str:
    """Legacy entry point. Prefer ``FirecrawlReader().read(...)``."""
    return FirecrawlReader().read(target_url, wait=wait, timeout=timeout)


def zai_reader(url: str, timeout: int = 20, return_format: str = "markdown") -> str:
    """Legacy entry point. Prefer ``ZaiReader().read(...)``."""
    return ZaiReader().read(url, timeout=timeout, return_format=return_format)


# Module-level config proxy for legacy ``from .engine import ZAI_API_KEY``.
ZAI_API_KEY = ZAI_API_KEY  # forward module-level legacy constant
_ = get_settings  # keep import live for future settings-aware extensions


__all__ = [
    "read_with_fallback",
    "scrape_with_fallback",
    "firecrawl_scrape",
    "zai_reader",
]
