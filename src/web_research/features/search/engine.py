"""Search backends: SearXNG, MiniMax, Z.AI, plus dispatcher."""

from __future__ import annotations

import urllib.error
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from web_research.shared.config import MINIMAX_API_KEY, SEARXNG_URL, ZAI_API_KEY
from web_research.shared.http import _debug, _encode_query, _get_json, _post_json, _warn

_TRACKING_PARAMS = {
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


def _canonical_url(url: str) -> str:
    """Normalize result URLs for dedup without changing what users see."""
    if not url:
        return ""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    query_items = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k not in _TRACKING_PARAMS
    ]
    query = urlencode(query_items, doseq=True)
    return urlunparse((parsed.scheme.lower(), netloc, path, "", query, ""))


def _unique_queries(query: str, queries: list[str] | None = None) -> list[str]:
    out = []
    seen = set()
    for q in [query, *(queries or [])]:
        q = q.strip()
        key = q.lower()
        if q and key not in seen:
            seen.add(key)
            out.append(q)
    return out


def _search_one_query(
    query: str, num: int, engine: str, cat: str, lang: str, time_range: str
) -> list[dict]:
    """Dispatch one query to the requested engine plus local fallback."""
    engines = [engine]
    if engine != "searxng":
        engines.append("searxng")

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

    with ThreadPoolExecutor(max_workers=min(len(engines), 2)) as ex:
        batches = list(ex.map(fetch, engines))

    results = []
    for batch in batches:
        results.extend(batch)
    return results


def search_backends(
    query: str,
    num: int,
    engine: str,
    cat: str,
    lang: str,
    time_range: str,
    queries: list[str] | None = None,
) -> list[dict]:
    """Dispatch to chosen engine, with SearXNG fallback and URL dedup."""
    seen_urls = set()
    results = []

    all_queries = _unique_queries(query, queries)
    _debug("search", f"engine={engine} queries={len(all_queries)} num={num}")
    for q in all_queries:
        batch = _search_one_query(q, num, engine, cat, lang, time_range)
        for r in batch:
            canonical = _canonical_url(r.get("url", ""))
            if canonical and canonical in seen_urls:
                continue
            if canonical:
                seen_urls.add(canonical)
            results.append(r)
        if len(results) >= num:
            break
    return results[:num]
