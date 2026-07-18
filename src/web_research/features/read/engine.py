"""Read dispatcher: backend resolution + Firecrawl→Z.AI fallback.

Backend-specific HTTP lives in ``backends/<name>.py``. This module is the
thin glue: pick a reader from the registry, try the requested one first,
fall back through the chain when one returns empty markdown.
"""

from __future__ import annotations

from web_research.shared.config import ZAI_API_KEY, get_settings
from web_research.shared.http import debug
from web_research.shared.robots import is_allowed

from . import backends  # noqa: F401 — re-exported so ``wr.reader.backends.<x>`` works
from .backends import FirecrawlReader, ZaiReader, build_reader


def _fallback_chain(engine: str) -> list[str]:
    """Resolve the engine order: requested → Firecrawl → Z.AI (if keyed) → HTML.

    The stdlib HTML reader is always appended last as a zero-dep, no-key,
    no-JS last resort so the chain never returns empty just because the two
    server-side readers are down.
    """
    chain = [engine]
    if engine != "firecrawl":
        chain.append("firecrawl")
    if "zai" not in chain and ZAI_API_KEY:
        chain.append("zai")
    if "html" not in chain:
        chain.append("html")
    return chain


# vs-soft-allow  — read_with_fallback kwargs mirror the public CLI flags
# (engine/wait/zai_timeout/respect_robots). Wrapping in a ReadOptions DTO would
# shuffle params without reducing coupling: this is the seam where CLI args land.
def read_with_fallback(
    url: str,
    *,
    engine: str = "firecrawl",
    wait: int = 0,
    zai_timeout: int = 20,
    respect_robots: bool = True,
) -> str:
    """Try the requested engine, then Firecrawl, Z.AI, then stdlib HTML.

    When ``respect_robots`` is True (default), URLs disallowed by the site's
    ``robots.txt`` are skipped and an empty string is returned. The robots
    check fails open (allows) when ``/robots.txt`` is unreachable.
    """
    if respect_robots and not is_allowed(url):
        debug("reader", f"robots.txt disallows {url}")
        return ""
    for eng in _fallback_chain(engine):
        # Keep the historic ``wr.reader.ZAI_API_KEY`` override effective.
        # The flat API exposed this module-level setting long before readers
        # became backend classes, and tests/consumers still patch it at runtime.
        if eng == "zai":
            zai_backend = ZaiReader(api_key=ZAI_API_KEY)
            debug("reader", f"trying {eng} for {url}")
            md = zai_backend.read(url, timeout=zai_timeout)
            if md:
                return md
            continue
        backend = build_reader(eng)
        if backend is None:
            continue
        debug("reader", f"trying {eng} for {url}")
        md = (
            backend.read(url, wait=wait, timeout=zai_timeout)
            if eng == "firecrawl"
            else backend.read(url, timeout=zai_timeout)
        )
        if md:
            return md
    return ""


def scrape_with_fallback(target_url: str, wait: int = 0, respect_robots: bool = True) -> str:
    """Backward-compatible entry used by ``mode_research``."""
    debug("reader", f"scraping {target_url}")
    return read_with_fallback(target_url, wait=wait, respect_robots=respect_robots)


# -- Legacy thin functions re-exported for the historic flat API --------------
# These exist so ``from web_research.features.read.engine import
# firecrawl_scrape`` keeps working. New code should use ``FirecrawlReader``
# from ``backends/firecrawl.py`` directly.


def firecrawl_scrape(target_url: str, wait: int = 0, timeout: int = 45) -> str:
    """Legacy entry point. Prefer ``FirecrawlReader().read(...)``."""
    return FirecrawlReader().read(target_url, wait=wait, timeout=timeout)


def zai_reader(url: str, timeout: int = 20, return_format: str = "markdown") -> str:
    """Legacy entry point. Prefer ``ZaiReader().read(...)``."""
    return ZaiReader(api_key=ZAI_API_KEY).read(
        url,
        timeout=timeout,
        return_format=return_format,
    )


# Module-level config proxy for legacy ``from .engine import ZAI_API_KEY``.
ZAI_API_KEY = ZAI_API_KEY  # forward module-level legacy constant
_ = get_settings  # keep import live for future settings-aware extensions


__all__ = [
    "read_with_fallback",
    "scrape_with_fallback",
    "firecrawl_scrape",
    "zai_reader",
]
