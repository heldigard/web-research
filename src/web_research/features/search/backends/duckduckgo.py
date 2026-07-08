"""DuckDuckGo HTML search backend (zero-dependency, no API key).

Hits the lightweight ``html.duckduckgo.com/html/`` endpoint and parses result
anchors with the standard-library ``html.parser``. Free, anonymous, and a
useful broad-result source alongside SearXNG. Result links are wrapped in a
DuckDuckGo redirect (``/l/?uddg=<encoded real url>``); ``_decode_ddg_href``
unwraps them so downstream ranking/dedup sees the canonical URL.

Fragility note: the HTML class names (``result__a`` / ``result__snippet``) are
DDG's, not ours. If DDG changes their markup, this backend returns fewer
results rather than crashing — the dispatcher still has the other engines.
"""

from __future__ import annotations

import urllib.error
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

from web_research.shared.http import default_client, urlencode, warn

from .base import SearchResult

# vs-soft-allow  — see backends/base.py; HTTP-semantic backend contract.

_DDG_HTML_URL = "https://html.duckduckgo.com/html/"


class DuckDuckGoBackend:
    """``GET {html_url}?q=...`` — anonymous, no auth, HTML scraping."""

    name = "duckduckgo"

    def __init__(self, base_url: str | None = None, **_unused: object) -> None:
        self.base_url = (base_url or _DDG_HTML_URL).rstrip("/")

    def search(  # vs-soft-allow  — backend contract; HTTP-semantic kwargs
        self,
        query: str,
        num: int,
        **_unused: object,
    ) -> list[SearchResult]:
        try:
            raw = default_client().get_bytes(
                f"{self.base_url}/?{urlencode({'q': query})}",
                timeout=20,
            )
        except urllib.error.URLError as e:
            warn("duckduckgo", str(e))
            return []
        except Exception as e:  # noqa: BLE001
            warn("duckduckgo", f"{type(e).__name__}: {e}")
            return []
        parser = _DDGResultParser()
        try:
            parser.feed(raw.decode("utf-8", errors="replace"))
            parser.close()
        except Exception:  # noqa: BLE001 — malformed HTML; keep what we parsed
            pass
        return _to_results(parser.results, num)


def _to_results(parsed: list[dict], num: int) -> list[SearchResult]:
    """Map parsed DDG rows to :class:`SearchResult`, dropping empty-URL hits."""
    out: list[SearchResult] = []
    for row in parsed:
        url = row.get("url", "").strip()
        if not url:
            continue
        out.append(
            SearchResult(
                title=row.get("title", "").strip(),
                url=url,
                content=row.get("snippet", "").strip(),
                engine="duckduckgo",
                source="duckduckgo",
                published_date="",
            )
        )
        if len(out) >= num:
            break
    return out


def _decode_ddg_href(href: str) -> str:
    """Unwrap DuckDuckGo's ``/l/?uddg=<encoded>`` redirect to the real URL."""
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return unquote(query["uddg"][0])
    return href


class _DDGResultParser(HTMLParser):
    """Collect ``result__a`` (url+title) and ``result__snippet`` (text) rows."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict] = []
        self._capture: str | None = None
        self._snippet_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = _class_list(attrs)
        if "result__a" in classes:
            href = _attr(attrs, "href") or ""
            self.results.append({"url": _decode_ddg_href(href), "title": "", "snippet": ""})
            self._capture = "title"
        elif "result__snippet" in classes and self.results:
            self._capture = "snippet"
            self._snippet_tag = tag

    def handle_endtag(self, tag: str) -> None:
        if self._capture == "title" and tag == "a":
            self._capture = None
        elif self._capture == "snippet" and tag == self._snippet_tag:
            self._capture = None
            self._snippet_tag = None

    def handle_data(self, data: str) -> None:
        if self._capture and self.results:
            self.results[-1][self._capture] += data


def _class_list(attrs: list[tuple[str, str | None]]) -> list[str]:
    """Return the ``class`` attribute tokens from an attrs list."""
    raw = _attr(attrs, "class") or ""
    return raw.split()


def _attr(attrs: list[tuple[str, str | None]], name: str) -> str | None:
    """First value for attribute ``name`` in ``attrs``, or ``None``."""
    for key, value in attrs:
        if key == name:
            return value
    return None
