"""Base protocol + SearchResult dataclass + parsing helpers for search backends.

Each backend (``searxng`` / ``minimax`` / ``zai``) lives in its own file
under this package and implements the duck-typed search contract. Adding
a new search source is one new file + one registry entry — no edits to
the dispatcher.

The contract (documented here, enforced at runtime via ``build_backend``):
    name: str
    search(query: str, num: int, **opts: object) -> list[SearchResult]
"""

# vs-soft-allow  — search backend contract is duck-typed by design; explicit
# Protocols here drift between backends because each accepts different
# backend-specific kwargs (SearXNG takes ``time_range``+``pageno``, Z.AI
# takes ``time_range``, MiniMax ignores them all). Python's duck typing wins.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchResult:
    """Canonical search hit. Same keys as the legacy dict for back-compat."""

    title: str
    url: str
    content: str
    engine: str
    source: str
    published_date: str = ""

    def to_dict(self) -> dict[str, str]:
        """Render as legacy ``dict`` for downstream formatters + tests."""
        return {
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "engine": self.engine,
            "source": self.source,
            "publishedDate": self.published_date,
        }


def tracking_params() -> set[str]:
    """Default tracking-param set stripped during URL canonicalization."""
    return {
        "fbclid",
        "gclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
        "spm",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_source",
        "utm_term",
    }


def normalize_url(url: str, tracking: set[str] | None = None) -> str:
    """Strip tracking params, lowercase host, drop trailing slash for dedup."""
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    if not url:
        return ""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    query_items = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k not in (tracking or tracking_params())
    ]
    return urlunparse(
        (
            parsed.scheme.lower(),
            netloc,
            path,
            "",
            urlencode(query_items, doseq=True),
            "",
        )
    )


# Type alias used by the dispatcher / registry. ``Any`` keeps backends free
# to declare backend-specific kwargs while still passing mypy.
SearchBackend = Any
