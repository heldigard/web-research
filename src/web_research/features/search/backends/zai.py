"""Z.AI web search backend (subscription-tier direct API)."""

from __future__ import annotations

import urllib.error

from web_research.shared.config import ZAI_API_KEY, get_settings
from web_research.shared.http import default_client, warn

from .base import SearchResult


def zai_recency(time_range: str) -> str:
    """Map SearXNG ``time_range`` values to Z.AI recency filter values."""
    return {
        "day": "oneDay",
        "week": "oneWeek",
        "month": "oneMonth",
        "year": "oneYear",
    }.get(time_range, "noLimit")


class ZaiBackend:
    """``POST {base_url}`` — Bearer auth, supports recency filter."""

    name = "zai"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else ZAI_API_KEY
        self.base_url = (base_url or settings.zai_search_url).rstrip("/")

    def search(  # vs-soft-allow  — backend contract
        self,
        query: str,
        num: int,
        *,
        time_range: str = "",
        **_unused: object,
    ) -> list[SearchResult]:
        if not self.api_key:
            return []
        try:
            data = default_client().post_json(
                f"{self.base_url}",
                {
                    "search_engine": "search-prime",
                    "search_query": query,
                    "count": num,
                    "search_recency_filter": zai_recency(time_range),
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=20,
            )
        except urllib.error.URLError as e:
            warn("zai", str(e))
            return []
        return [_to_result(r) for r in (data.get("search_result") or [])[:num]]


def _to_result(r: dict) -> SearchResult:
    """Map a Z.AI ``search_result[]`` row to :class:`SearchResult`."""
    return SearchResult(
        title=(r.get("title") or "").strip(),
        url=r.get("link") or "",
        content=(r.get("content") or "").strip(),
        engine=r.get("media") or "zai",
        source="zai",
        published_date=r.get("publish_date") or "",
    )
