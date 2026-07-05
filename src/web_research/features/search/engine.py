"""Search dispatcher: query fan-out, URL dedup, dict projection.

This module is the thin glue between search backends. All backend-specific
HTTP lives in ``backends/<name>.py``; this file only orchestrates:

1. Resolve a backend instance from the registry by name.
2. Fan out across an optional expansion query set (smart mode).
3. Merge with a SearXNG fallback (broad/fresh when primary is paid).
4. Deduplicate by canonical URL (tracking-param-stripped).
5. Project :class:`SearchResult` back to ``dict`` for downstream callers.

Returned dicts preserve the legacy keys (``title`` / ``url`` / ``content``
/ ``engine`` / ``source`` / ``publishedDate``) so existing formatters and
tests keep working without churn.
"""

# vs-soft-allow  — dispatcher signatures mirror the public CLI flags (engine,
# cat, lang, time_range, queries). Wrapping in a ``SearchRequest`` DTO would
# shuffle the params without reducing coupling: this is the legitimate seam
# where CLI args land.

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from web_research.shared.http import debug, warn

from . import backends  # noqa: F401 — re-exported so ``wr.search.backends.<x>`` works for tests
from .backends import (
    SearchResult,
    SearXNGBackend,
    build_backend,
    normalize_url,
    tracking_params,
)
from .backends.base import SearchBackend

_TRACKING = tracking_params()


def _unique_queries(query: str, queries: list[str] | None = None) -> list[str]:
    """De-dup the query + expansion list (case-insensitive)."""
    out: list[str] = []
    seen: set[str] = set()
    for q in [query, *(queries or [])]:
        q = q.strip()
        key = q.lower()
        if q and key not in seen:
            seen.add(key)
            out.append(q)
    return out


def _search_one_query(
    query: str,
    num: int,
    engine: str,
    cat: str,
    lang: str,
    time_range: str,
) -> list[dict]:
    """Run the requested engine plus a SearXNG fallback, return merged dicts.

    SearXNG is appended as a fallback when the primary engine is paid
    (MiniMax / Z.AI) so free broad results supplement the subscription
    results without duplicating them (URL dedup downstream).
    """
    instances: list[SearchBackend] = []
    primary = build_backend(engine)
    if primary is not None:
        instances.append(primary)
    if engine != "searxng":
        instances.append(SearXNGBackend(cat=cat, lang=lang))

    def fetch(b: SearchBackend) -> list[SearchResult]:
        try:
            opts: dict[str, object] = {"time_range": time_range} if b.name == "zai" else {}
            return b.search(query, num, **opts)
        except Exception as e:  # noqa: BLE001 — backends already warn, this is the safety net
            warn(b.name, str(e))
            return []

    with ThreadPoolExecutor(max_workers=min(len(instances), 2)) as ex:
        batches = list(ex.map(fetch, instances))

    results: list[SearchResult] = []
    for batch in batches:
        results.extend(batch)
    return [r.to_dict() for r in results]


def search_backends(  # vs-soft-allow  — CLI-arg passthrough
    query: str,
    num: int,
    engine: str,
    cat: str,
    lang: str,
    time_range: str,
    queries: list[str] | None = None,
) -> list[dict]:
    """Dispatch to the chosen engine + SearXNG fallback, return deduped dicts.

    Iterates ``[query, *queries]`` until ``num`` unique URLs are collected.
    Tracking params (``utm_*``, ``fbclid``, ...) are stripped during
    canonicalization so the same article under different campaign tags
    collapses to one entry.
    """
    seen: set[str] = set()
    out: list[dict] = []

    all_queries = _unique_queries(query, queries)
    debug("search", f"engine={engine} queries={len(all_queries)} num={num}")
    for q in all_queries:
        batch = _search_one_query(q, num, engine, cat, lang, time_range)
        out = _absorb_dedup(batch, out, seen, num)
        if len(out) >= num:
            break
    return out[:num]


def _absorb_dedup(
    batch: list[dict],
    out: list[dict],
    seen: set[str],
    num: int,
) -> list[dict]:
    """Append ``batch`` into ``out`` keeping only URLs new to ``seen``."""
    for r in batch:
        canonical = normalize_url(r.get("url", ""), _TRACKING)
        if canonical and canonical in seen:
            continue
        if canonical:
            seen.add(canonical)
        out.append(r)
    return out


# -- Legacy thin functions re-exported for the historic flat API --------------
# These exist so ``from web_research.features.search.engine import
# searxng_search`` keeps working. New code should use ``SearXNGBackend``
# from ``backends/searxng.py`` directly.


def searxng_search(
    query: str,
    num: int,
    cat: str = "general",
    lang: str = "en",
    time_range: str = "",
    pageno: int = 1,
) -> list[dict]:
    """Legacy entry point. Prefer ``SearXNGBackend().search(...)``."""
    backend = SearXNGBackend(cat=cat, lang=lang)
    return [r.to_dict() for r in backend.search(query, num, time_range=time_range, pageno=pageno)]


def minimax_search(query: str, num: int) -> list[dict]:
    """Legacy entry point. Prefer ``MinimaxBackend().search(...)``."""
    from .backends import MinimaxBackend

    return [r.to_dict() for r in MinimaxBackend().search(query, num)]


def zai_search(query: str, num: int, recency: str = "noLimit") -> list[dict]:
    """Legacy entry point. Prefer ``ZaiBackend().search(...)``."""
    from .backends import ZaiBackend

    return [r.to_dict() for r in ZaiBackend().search(query, num, time_range=recency)]


# Re-exported for downstream callers that imported them via this module.
__all__ = [
    "search_backends",
    "searxng_search",
    "minimax_search",
    "zai_search",
]
