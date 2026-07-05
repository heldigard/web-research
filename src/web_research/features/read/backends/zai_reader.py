"""Z.AI reader backend (subscription-tier direct API)."""

from __future__ import annotations

import urllib.error

from web_research.shared.config import ZAI_API_KEY, get_settings
from web_research.shared.http import default_client, warn

# vs-soft-allow  — see backends/base.py; HTTP-semantic reader contract.


class ZaiReader:
    """``POST {zai_reader_url}`` — Bearer auth, subscription only."""

    name = "zai"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else ZAI_API_KEY
        self.base_url = (base_url or get_settings().zai_reader_url).rstrip("/")

    def read(self, url: str, *, timeout: int = 20, return_format: str = "markdown") -> str:
        """Return markdown (with `# title` prefix when available) or empty string."""
        if not self.api_key:
            return ""
        data = _fetch(self, url, timeout, return_format)
        if not data:
            return ""
        return _render_page(data.get("reader_result") or {})


def _fetch(reader: ZaiReader, url: str, timeout: int, return_format: str) -> dict | None:
    """POST the reader request and swallow network errors. Returns parsed JSON or ``None``."""
    try:
        return default_client().post_json(
            f"{reader.base_url}",
            {
                "url": url,
                "timeout": timeout,
                "return_format": return_format,
            },
            headers={"Authorization": f"Bearer {reader.api_key}"},
            timeout=timeout + 10,
        )
    except urllib.error.URLError as e:
        warn("zai-reader", str(e))
        return None
    except Exception as e:  # noqa: BLE001
        warn("zai-reader", f"{type(e).__name__}: {e}")
        return None


def _render_page(result: dict) -> str:
    """Format a Z.AI ``reader_result`` block as markdown."""
    content = result.get("content") or ""
    title = result.get("title") or ""
    if title and content:
        return f"# {title}\n\n{content}"
    return content
