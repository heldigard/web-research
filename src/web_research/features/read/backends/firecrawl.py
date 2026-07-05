"""Firecrawl backend (self-hosted :3002 — JS-rendered scraping)."""

from __future__ import annotations

import urllib.error

from web_research.shared.config import get_settings
from web_research.shared.http import default_client, warn

# vs-soft-allow  — see backends/base.py; HTTP-semantic reader contract.


class FirecrawlReader:
    """``POST {base_url}/v1/scrape`` — Bearer auth, JS-rendered pages."""

    name = "firecrawl"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.firecrawl_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.firecrawl_api_key

    def read(self, url: str, *, wait: int = 0, timeout: int = 45) -> str:
        """Return markdown or empty string on failure."""
        payload: dict[str, object] = {
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": True,
        }
        if wait:
            payload["waitFor"] = wait
        try:
            data = default_client().post_json(
                f"{self.base_url}/v1/scrape",
                payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=timeout,
            )
            if data.get("success"):
                return (data.get("data") or {}).get("markdown") or ""
            return ""
        except urllib.error.URLError as e:
            warn("firecrawl", f"{url} -> {e}")
            return ""
        except Exception as e:  # noqa: BLE001
            warn("firecrawl", f"{url} -> {type(e).__name__}: {e}")
            return ""
