"""SearXNG backend (self-hosted metasearch)."""

from __future__ import annotations

from web_research.shared.config import get_settings
from web_research.shared.http import default_client, urlencode

from .base import SearchResult

# vs-soft-allow  — see backends/base.py; HTTP-semantic backend contract.


class SearXNGBackend:
    """``GET {base_url}/search?format=json``. Zero auth, local-first."""

    name = "searxng"

    def __init__(
        self,
        base_url: str | None = None,
        *,
        cat: str = "general",
        lang: str = "en",
    ) -> None:
        self.base_url = (base_url or get_settings().searxng_url).rstrip("/")
        self.cat = cat
        self.lang = lang

    def search(  # vs-soft-allow  — backend contract; HTTP-semantic kwargs
        self,
        query: str,
        num: int,
        *,
        cat: str | None = None,
        lang: str | None = None,
        time_range: str = "",
        pageno: int = 1,
        **_unused: object,
    ) -> list[SearchResult]:
        params: dict[str, str] = {
            "q": query,
            "format": "json",
            "categories": cat or self.cat,
            "language": lang or self.lang,
            "pageno": str(pageno),
        }
        if time_range:
            params["time_range"] = time_range
        url = f"{self.base_url}/search?{urlencode(params)}"
        data = default_client().get_json(url)
        return [_to_result(r) for r in (data.get("results") or [])[:num]]


def _to_result(r: dict) -> SearchResult:
    """Map a SearXNG result row to :class:`SearchResult` (no nested builders)."""
    return SearchResult(
        title=(r.get("title") or "").strip(),
        url=r.get("url") or "",
        content=(r.get("content") or "").strip(),
        engine=r.get("engine") or "",
        source="searxng",
        published_date=r.get("publishedDate") or "",
    )
