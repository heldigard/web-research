"""Search backends: SearXNG, MiniMax, Z.AI, plus dispatcher."""

from __future__ import annotations

import urllib.error
from concurrent.futures import ThreadPoolExecutor

from web_research.shared.config import MINIMAX_API_KEY, SEARXNG_URL, ZAI_API_KEY
from web_research.shared.http import _debug, _encode_query, _get_json, _post_json, _warn


def searxng_search(
    query: str,
    num: int,
    cat: str = "general",
    lang: str = "en",
    time_range: str = "",
    pageno: int = 1,
) -> list[dict]:
    """Return cleaned SearXNG results."""
    params: dict[str, str] = {
        "q": query,
        "format": "json",
        "categories": cat,
        "language": lang,
        "pageno": str(pageno),
    }
    if time_range:
        params["time_range"] = time_range
    url = f"{SEARXNG_URL}/search?{_encode_query(params)}"
    data = _get_json(url)
    out = []
    for r in data.get("results", [])[:num]:
        out.append(
            {
                "title": (r.get("title") or "").strip(),
                "url": r.get("url") or "",
                "content": (r.get("content") or "").strip(),
                "engine": r.get("engine") or "",
                "publishedDate": r.get("publishedDate") or "",
                "source": "searxng",
            }
        )
    return out


def minimax_search(query: str, num: int) -> list[dict]:
    """Direct MiniMax web search API."""
    if not MINIMAX_API_KEY:
        return []
    try:
        data = _post_json(
            "https://api.minimax.io/v1/coding_plan/search",
            {"q": query},
            headers={
                "Authorization": f"Bearer {MINIMAX_API_KEY}",
                "MM-API-Source": "claude-web-research",
            },
            timeout=20,
        )
        out = []
        for r in (data.get("organic") or [])[:num]:
            out.append(
                {
                    "title": (r.get("title") or "").strip(),
                    "url": r.get("link") or "",
                    "content": (r.get("snippet") or "").strip(),
                    "engine": "minimax",
                    "publishedDate": r.get("date") or "",
                    "source": "minimax",
                }
            )
        return out
    except urllib.error.URLError as e:
        _warn("minimax", str(e))
        return []


def zai_search(query: str, num: int, recency: str = "noLimit") -> list[dict]:
    """Direct Z.AI web search API."""
    if not ZAI_API_KEY:
        return []
    try:
        data = _post_json(
            "https://api.z.ai/api/paas/v4/web_search",
            {
                "search_engine": "search-prime",
                "search_query": query,
                "count": num,
                "search_recency_filter": recency,
            },
            headers={"Authorization": f"Bearer {ZAI_API_KEY}"},
            timeout=20,
        )
        out = []
        for r in (data.get("search_result") or [])[:num]:
            out.append(
                {
                    "title": (r.get("title") or "").strip(),
                    "url": r.get("link") or "",
                    "content": (r.get("content") or "").strip(),
                    "engine": r.get("media") or "zai",
                    "publishedDate": r.get("publish_date") or "",
                    "source": "zai",
                }
            )
        return out
    except urllib.error.URLError as e:
        _warn("zai", str(e))
        return []


def _zai_recency(time_range: str) -> str:
    """Map SearXNG time_range values to Z.AI recency filter values."""
    return {
        "day": "oneDay",
        "week": "oneWeek",
        "month": "oneMonth",
        "year": "oneYear",
    }.get(time_range, "noLimit")


def search_backends(
    query: str, num: int, engine: str, cat: str, lang: str, time_range: str
) -> list[dict]:
    """Dispatch to chosen engine, with SearXNG as default and fallback."""
    engines = [engine]
    if engine != "searxng":
        engines.append("searxng")
    seen_urls = set()
    results = []

    def fetch(eng: str) -> list[dict]:
        try:
            if eng == "minimax":
                return minimax_search(query, num)
            if eng == "zai":
                return zai_search(query, num, _zai_recency(time_range))
            return searxng_search(query, num, cat, lang, time_range)
        except urllib.error.URLError as e:
            _warn(eng, str(e))
            return []

    _debug("search", f"engines={engines} num={num}")
    with ThreadPoolExecutor(max_workers=min(len(engines), 2)) as ex:
        batches = list(ex.map(fetch, engines))

    for batch in batches:
        for r in batch:
            if r["url"] and r["url"] in seen_urls:
                continue
            if r["url"]:
                seen_urls.add(r["url"])
            results.append(r)
        if len(results) >= num:
            break
    return results[:num]
