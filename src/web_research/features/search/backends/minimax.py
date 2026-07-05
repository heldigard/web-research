"""MiniMax web search backend (subscription-tier direct API)."""

from __future__ import annotations

import urllib.error

from web_research.shared.config import MINIMAX_API_KEY, get_settings
from web_research.shared.http import default_client, warn

from .base import SearchResult

# vs-soft-allow  — see backends/base.py; HTTP-semantic backend contract.
#
# Legacy module-level ``MINIMAX_API_KEY`` retained so existing tests
# using ``patch.object(wr.search.backends.minimax, "MINIMAX_API_KEY",
# ...)`` keep working through the split refactor.


class MinimaxBackend:
    """``POST {base_url}`` — Bearer auth, subscription only."""

    name = "minimax"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else MINIMAX_API_KEY
        self.base_url = (base_url or get_settings().minimax_url).rstrip("/")

    def search(  # vs-soft-allow  — backend contract
        self,
        query: str,
        num: int,
        **_unused: object,
    ) -> list[SearchResult]:
        if not self.api_key:
            return []
        try:
            data = default_client().post_json(
                f"{self.base_url}",
                {"q": query},
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "MM-API-Source": "claude-web-research",
                },
                timeout=20,
            )
        except urllib.error.URLError as e:
            warn("minimax", str(e))
            return []
        return [_to_result(r) for r in (data.get("organic") or [])[:num]]


def _to_result(r: dict) -> SearchResult:
    """Map a MiniMax ``organic[]`` row to :class:`SearchResult`."""
    return SearchResult(
        title=(r.get("title") or "").strip(),
        url=r.get("link") or "",
        content=(r.get("snippet") or "").strip(),
        engine="minimax",
        source="minimax",
        published_date=r.get("date") or "",
    )
