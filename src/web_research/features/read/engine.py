"""Page readers: Firecrawl local and Z.AI reader fallback."""

from __future__ import annotations

import urllib.error

from web_research.shared.config import FC_API_KEY, FC_URL, ZAI_API_KEY
from web_research.shared.http import _debug, _post_json, _warn


def firecrawl_scrape(target_url: str, wait: int = 0, timeout: int = 45) -> str:
    """Return markdown for a URL via Firecrawl /v1/scrape."""
    payload: dict = {
        "url": target_url,
        "formats": ["markdown"],
        "onlyMainContent": True,
    }
    if wait:
        payload["waitFor"] = wait
    try:
        data = _post_json(
            f"{FC_URL}/v1/scrape",
            payload,
            headers={"Authorization": f"Bearer {FC_API_KEY}"},
            timeout=timeout,
        )
        if data.get("success"):
            return (data.get("data") or {}).get("markdown") or ""
    except urllib.error.URLError as e:
        _warn("firecrawl", f"{target_url} -> {e}")
    except Exception as e:  # noqa: BLE001
        _warn("firecrawl", f"{target_url} -> {type(e).__name__}: {e}")
    return ""


def zai_reader(url: str, timeout: int = 20, return_format: str = "markdown") -> str:
    """Direct Z.AI web reader API."""
    if not ZAI_API_KEY:
        return ""
    try:
        data = _post_json(
            "https://api.z.ai/api/paas/v4/reader",
            {
                "url": url,
                "timeout": timeout,
                "return_format": return_format,
            },
            headers={"Authorization": f"Bearer {ZAI_API_KEY}"},
            timeout=timeout + 10,
        )
        result = data.get("reader_result") or {}
        content = result.get("content") or ""
        title = result.get("title") or ""
        if title and content:
            return f"# {title}\n\n{content}"
        return content
    except urllib.error.URLError as e:
        _warn("zai-reader", str(e))
        return ""
    except Exception as e:  # noqa: BLE001
        _warn("zai-reader", f"{type(e).__name__}: {e}")
        return ""


def scrape_with_fallback(target_url: str, wait: int = 0) -> str:
    """Scrape via Firecrawl; fall back to Z.AI reader if available."""
    _debug("reader", f"scraping {target_url}")
    md = firecrawl_scrape(target_url, wait=wait)
    if md:
        return md
    if ZAI_API_KEY:
        _debug("reader", f"firecrawl empty, trying zai: {target_url}")
        return zai_reader(target_url)
    return ""
